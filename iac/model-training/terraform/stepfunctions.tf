# Este flujo es independiente del batch de limpieza y Gold del data-platform.
# Inicia EC2, espera a que SSM la vea Online, ejecuta train.py y apaga EC2.

locals {
  training_command = <<-SHELL
    set -eu
    export HOME=/root
    export XDG_CACHE_HOME=/root/.cache
    mkdir -p "$HOME/.duckdb/extensions" "$XDG_CACHE_HOME" /mnt/finsir-duckdb-tmp "$(dirname '${var.training_repo_path}')"

    if ! command -v git >/dev/null 2>&1 || ! command -v python3.12 >/dev/null 2>&1 || ! (ldconfig -p 2>/dev/null | grep -q 'libgomp.so.1'); then
      dnf install -y git libgomp python3.12 python3.12-pip
    fi

    REPO='${var.training_repo_path}'
    BRANCH='${var.training_repo_branch}'
    if git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      git -C "$REPO" fetch origin "$BRANCH"
      git -C "$REPO" checkout -B "$BRANCH" FETCH_HEAD
    else
      if [ -d "$REPO" ] && [ -n "$(find "$REPO" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
        echo "La ruta $REPO ya existe, no esta vacia y no es un checkout Git." >&2
        exit 1
      fi
      git clone --branch "$BRANCH" --single-branch '${var.training_repo_url}' "$REPO"
    fi

    MODEL_DIR="$REPO/iac/model-training"
    REQUIREMENTS="$MODEL_DIR/requirements.txt"
    VENV="$REPO/.venv-training"
    if [ ! -x "$VENV/bin/python" ]; then python3.12 -m venv "$VENV"; fi
    PYTHON="$VENV/bin/python"
    REQUIREMENTS_HASH="$(sha256sum "$REQUIREMENTS" | awk '{print $1}')"
    REQUIREMENTS_MARKER="$VENV/.requirements.sha256"
    if [ ! -f "$REQUIREMENTS_MARKER" ] || [ "$(cat "$REQUIREMENTS_MARKER")" != "$REQUIREMENTS_HASH" ]; then
      "$PYTHON" -m pip install --upgrade pip
      "$PYTHON" -m pip install -r "$REQUIREMENTS"
      printf '%s\n' "$REQUIREMENTS_HASH" > "$REQUIREMENTS_MARKER"
    fi

    cd "$MODEL_DIR"
    LOG="/mnt/finsir-duckdb-tmp/model-training-$(date -u +%Y%m%dT%H%M%SZ).log"
    set +e
    "$PYTHON" train.py --bucket '${local.bucket_name}' --region '${var.region}' \
      --output-dir ./artifacts --duckdb-temp-dir /mnt/finsir-duckdb-tmp \
      --artifact-s3-uri 's3://${local.bucket_name}/models/production/finsir.joblib' \
      > "$LOG" 2>&1
    TRAIN_EXIT=$?
    tail -n 100 "$LOG" || true
    exit "$TRAIN_EXIT"
  SHELL

  training_definition = {
    Comment = "Entrena FINSIR en EC2 desde Gold, independiente del flujo de limpieza"
    StartAt = "DescribirEC2"
    States = {
      DescribirEC2 = {
        Type     = "Task"
        Resource = "arn:aws:states:::aws-sdk:ec2:describeInstances"
        Parameters = {
          InstanceIds = [aws_instance.training[0].id]
        }
        ResultPath = "$.ec2Info"
        Catch = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.failure", Next = "EntrenamientoFallido" }]
        Next  = "EstadoEC2"
      }
      EstadoEC2 = {
        Type = "Choice"
        Choices = [
          { Variable = "$.ec2Info.Reservations[0].Instances[0].State.Name", StringEquals = "running", Next = "InicializarEsperaSSM" },
          { Variable = "$.ec2Info.Reservations[0].Instances[0].State.Name", StringEquals = "stopped", Next = "IniciarEC2" },
          { Variable = "$.ec2Info.Reservations[0].Instances[0].State.Name", StringEquals = "terminated", Next = "EntrenamientoFallido" },
          { Variable = "$.ec2Info.Reservations[0].Instances[0].State.Name", StringEquals = "shutting-down", Next = "EntrenamientoFallido" },
        ]
        Default = "EsperarEC2"
      }
      EsperarEC2 = { Type = "Wait", Seconds = 20, Next = "DescribirEC2" }
      IniciarEC2 = {
        Type     = "Task"
        Resource = "arn:aws:states:::aws-sdk:ec2:startInstances"
        Parameters = {
          InstanceIds = [aws_instance.training[0].id]
        }
        ResultPath = "$.ec2Start"
        Catch = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.failure", Next = "EntrenamientoFallido" }]
        Next  = "InicializarEsperaSSM"
      }
      InicializarEsperaSSM = {
        Type       = "Pass"
        Result     = { count = 0 }
        ResultPath = "$.ssmPoll"
        Next       = "EsperarSSM"
      }
      EsperarSSM = { Type = "Wait", Seconds = 20, Next = "ConsultarSSM" }
      ConsultarSSM = {
        Type     = "Task"
        Resource = "arn:aws:states:::aws-sdk:ssm:describeInstanceInformation"
        Parameters = {
          Filters = [{ Key = "InstanceIds", Values = [aws_instance.training[0].id] }]
        }
        ResultPath = "$.ssmInfo"
        Retry = [{ ErrorEquals = ["Ssm.InternalServerError", "Ssm.ThrottlingException"], IntervalSeconds = 10, BackoffRate = 2, MaxAttempts = 3 }]
        Catch = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.failure", Next = "DetenerEC2Fallida" }]
        Next  = "EstadoSSM"
      }
      EstadoSSM = {
        Type = "Choice"
        Choices = [
          { Variable = "$.ssmInfo.InstanceInformationList[0].PingStatus", IsPresent = false, Next = "IncrementarEsperaSSM" },
          { Variable = "$.ssmInfo.InstanceInformationList[0].PingStatus", StringEquals = "Online", Next = "EjecutarEntrenamiento" },
        ]
        Default = "IncrementarEsperaSSM"
      }
      IncrementarEsperaSSM = {
        Type       = "Pass"
        Parameters = { "count.$" = "States.MathAdd($.ssmPoll.count, 1)" }
        ResultPath = "$.ssmPoll"
        Next       = "LimiteEsperaSSM"
      }
      LimiteEsperaSSM = {
        Type = "Choice"
        Choices = [{ Variable = "$.ssmPoll.count", NumericGreaterThan = 30, Next = "DetenerEC2Fallida" }]
        Default = "EsperarSSM"
      }
      EjecutarEntrenamiento = {
        Type     = "Task"
        Resource = "arn:aws:states:::aws-sdk:ssm:sendCommand"
        Parameters = {
          DocumentName = "AWS-RunShellScript"
          InstanceIds  = [aws_instance.training[0].id]
          # The Terraform file may use CRLF on Windows; strip carriage returns
          # so AWS-RunShellScript receives valid Unix shell lines.
          Parameters = { commands = [replace(local.training_command, "\r", "")], executionTimeout = ["86400"] }
        }
        ResultPath = "$.trainingCommand"
        Retry = [{ ErrorEquals = ["Ssm.InternalServerError", "Ssm.ThrottlingException"], IntervalSeconds = 10, BackoffRate = 2, MaxAttempts = 3 }]
        Catch = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.failure", Next = "DetenerEC2Fallida" }]
        Next  = "EsperarResultadoEntrenamiento"
      }
      EsperarResultadoEntrenamiento = { Type = "Wait", Seconds = 20, Next = "ConsultarResultadoEntrenamiento" }
      ConsultarResultadoEntrenamiento = {
        Type     = "Task"
        Resource = "arn:aws:states:::aws-sdk:ssm:getCommandInvocation"
        Parameters = {
          "CommandId.$" = "$.trainingCommand.Command.CommandId"
          InstanceId    = aws_instance.training[0].id
        }
        ResultPath = "$.trainingInvocation"
        Retry = [{ ErrorEquals = ["Ssm.InvocationDoesNotExist", "Ssm.InternalServerError", "Ssm.ThrottlingException"], IntervalSeconds = 10, BackoffRate = 2, MaxAttempts = 6 }]
        Catch = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.failure", Next = "DetenerEC2Fallida" }]
        Next  = "EstadoEntrenamiento"
      }
      EstadoEntrenamiento = {
        Type = "Choice"
        Choices = [
          { Variable = "$.trainingInvocation.Status", StringEquals = "Success", Next = "DetenerEC2Exitosa" },
          { Variable = "$.trainingInvocation.Status", StringEquals = "Failed", Next = "DetenerEC2Fallida" },
          { Variable = "$.trainingInvocation.Status", StringEquals = "TimedOut", Next = "DetenerEC2Fallida" },
          { Variable = "$.trainingInvocation.Status", StringEquals = "Cancelled", Next = "DetenerEC2Fallida" },
          { Variable = "$.trainingInvocation.Status", StringEquals = "Undeliverable", Next = "DetenerEC2Fallida" },
          { Variable = "$.trainingInvocation.Status", StringEquals = "Terminated", Next = "DetenerEC2Fallida" },
        ]
        Default = "EsperarResultadoEntrenamiento"
      }
      DetenerEC2Exitosa = {
        Type     = "Task"
        Resource = "arn:aws:states:::aws-sdk:ec2:stopInstances"
        Parameters = { InstanceIds = [aws_instance.training[0].id] }
        ResultPath = "$.ec2Stop"
        Catch = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.stopFailure", Next = "EntrenamientoFallido" }]
        Next  = "EntrenamientoExitoso"
      }
      DetenerEC2Fallida = {
        Type     = "Task"
        Resource = "arn:aws:states:::aws-sdk:ec2:stopInstances"
        Parameters = { InstanceIds = [aws_instance.training[0].id] }
        ResultPath = "$.ec2Stop"
        Catch = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.stopFailure", Next = "EntrenamientoFallido" }]
        Next  = "EntrenamientoFallido"
      }
      EntrenamientoExitoso = { Type = "Succeed" }
      EntrenamientoFallido = { Type = "Fail", Error = "ModelTrainingFailed", Cause = "Falló el entrenamiento. Consulta la salida de Systems Manager Run Command en esta ejecución." }
    }
  }
}

data "aws_iam_policy_document" "training_sfn_assume" {
  count = var.create_instance ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "training_sfn" {
  count              = var.create_instance ? 1 : 0
  name               = "finsir-model-training-sfn"
  assume_role_policy = data.aws_iam_policy_document.training_sfn_assume[0].json
}

data "aws_iam_policy_document" "training_sfn" {
  count = var.create_instance ? 1 : 0

  statement {
    sid       = "ManageTrainingInstance"
    actions   = ["ec2:StartInstances", "ec2:StopInstances"]
    resources = [aws_instance.training[0].arn]
  }

  statement {
    sid       = "DescribeTrainingInstance"
    actions   = ["ec2:DescribeInstances"]
    resources = ["*"]
  }

  statement {
    sid       = "SendTrainingCommand"
    actions   = ["ssm:SendCommand"]
    resources = [
      aws_instance.training[0].arn,
      "arn:${data.aws_partition.current.partition}:ssm:${var.region}::document/AWS-RunShellScript",
    ]
  }

  statement {
    sid       = "ReadTrainingCommandStatus"
    actions   = ["ssm:GetCommandInvocation", "ssm:DescribeInstanceInformation"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "training_sfn" {
  count  = var.create_instance ? 1 : 0
  name   = "finsir-model-training-sfn"
  role   = aws_iam_role.training_sfn[0].id
  policy = data.aws_iam_policy_document.training_sfn[0].json
}

resource "aws_sfn_state_machine" "training" {
  count      = var.create_instance ? 1 : 0
  name       = "finsir-model-training"
  role_arn   = aws_iam_role.training_sfn[0].arn
  type       = "STANDARD"
  definition = jsonencode(local.training_definition)
}

# Programacion opcional y separada: por defecto el entrenamiento solo se inicia
# manualmente o desde otra automatizacion que invoque esta State Machine.
data "aws_iam_policy_document" "training_events_assume" {
  count = var.create_instance && var.training_schedule_enabled ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "training_events" {
  count              = var.create_instance && var.training_schedule_enabled ? 1 : 0
  name               = "finsir-model-training-events"
  assume_role_policy = data.aws_iam_policy_document.training_events_assume[0].json
}

resource "aws_iam_role_policy" "training_events" {
  count = var.create_instance && var.training_schedule_enabled ? 1 : 0
  name  = "finsir-model-training-start-sfn"
  role  = aws_iam_role.training_events[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["states:StartExecution"]
      Resource = aws_sfn_state_machine.training[0].arn
    }]
  })
}

resource "aws_cloudwatch_event_rule" "training_schedule" {
  count               = var.create_instance && var.training_schedule_enabled ? 1 : 0
  name                = "finsir-model-training-schedule"
  description         = "Inicia el entrenamiento FINSIR de forma independiente al batch de limpieza."
  schedule_expression = var.training_schedule_expression
  state               = "ENABLED"
}

resource "aws_cloudwatch_event_target" "training_schedule" {
  count     = var.create_instance && var.training_schedule_enabled ? 1 : 0
  rule      = aws_cloudwatch_event_rule.training_schedule[0].name
  arn       = aws_sfn_state_machine.training[0].arn
  role_arn  = aws_iam_role.training_events[0].arn
  input     = "{}"
}
