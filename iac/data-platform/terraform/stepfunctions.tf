# Orquestacion del batch: limpieza (bronze -> silver) y luego, en paralelo,
# todos los jobs gold (silver -> gold). Agregar una tabla gold nueva es anadir
# su job a local.gold_job_names en main.tf; aqui no hay que tocar nada.

locals {
  state_machine_name = "${var.project}-batch-diario"

  # Definicion de la maquina de estados (Amazon States Language).
  # 1) Limpieza sincrona (.sync espera a que el Glue job termine).
  # 2) Map que corre cada job gold en paralelo, tambien sincrono.
  states_definition = {
    Comment = "FINSIR batch: limpieza y luego tablas gold en paralelo"
    StartAt = "Limpieza"
    States = {
      Limpieza = {
        Type     = "Task"
        Resource = "arn:aws:states:::glue:startJobRun.sync"
        Parameters = {
          JobName = aws_glue_job.limpieza.name
        }
        Next = "TablasGold"
      }
      TablasGold = {
        Type           = "Map"
        ItemsPath      = "$.gold_jobs"
        MaxConcurrency = 0 # 0 = sin limite: todos los jobs gold a la vez
        Iterator = {
          StartAt = "JobGold"
          States = {
            JobGold = {
              Type     = "Task"
              Resource = "arn:aws:states:::glue:startJobRun.sync"
              Parameters = {
                "JobName.$" = "$"
              }
              End = true
            }
          }
        }
        End = true
      }
    }
  }
}

data "aws_iam_policy_document" "sfn_assume" {
  count = var.create_orchestration ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sfn" {
  count = var.create_orchestration ? 1 : 0

  name               = "${var.project}-sfn-role"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume[0].json
}

# Permisos para arrancar/seguir/parar los jobs de Glue de este proyecto.
# El patron .sync necesita ademas la regla gestionada de EventBridge que Glue
# usa para avisar que el job termino (recurso con nombre fijo de AWS).
data "aws_iam_policy_document" "sfn" {
  count = var.create_orchestration ? 1 : 0

  statement {
    sid       = "RunGlueJobs"
    actions   = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns", "glue:BatchStopJobRun"]
    resources = ["*"] # Glue job runs no soportan ARN por recurso en estas acciones
  }

  statement {
    sid     = "SyncCallback"
    actions = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
    resources = [
      "arn:aws:events:${var.region}:${local.account_id}:rule/StepFunctionsGetEventsForGlueJobRule",
    ]
  }
}

resource "aws_iam_role_policy" "sfn" {
  count = var.create_orchestration ? 1 : 0

  name   = "${var.project}-sfn-glue"
  role   = aws_iam_role.sfn[0].id
  policy = data.aws_iam_policy_document.sfn[0].json
}

resource "aws_sfn_state_machine" "batch" {
  count = var.create_orchestration ? 1 : 0

  name     = local.state_machine_name
  role_arn = aws_iam_role.sfn[0].arn
  type     = "STANDARD"

  definition = jsonencode(local.states_definition)
}
