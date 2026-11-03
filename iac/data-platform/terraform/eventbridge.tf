# Dispara la orquestacion del batch segun un horario. La regla le pasa a la
# Step Functions la lista de jobs gold como input (campo gold_jobs), que el Map
# recorre. Apagada por defecto (schedule_enabled = false).

resource "aws_cloudwatch_event_rule" "batch_diario" {
  count = var.create_orchestration ? 1 : 0

  name                = "${var.project}-pipeline-diario"
  description         = "Dispara la orquestacion del batch de FINSIR"
  schedule_expression = var.schedule_expression
  state               = var.schedule_enabled ? "ENABLED" : "DISABLED"
}

data "aws_iam_policy_document" "events_assume" {
  count = var.create_orchestration ? 1 : 0

  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "events" {
  count = var.create_orchestration ? 1 : 0

  name               = "${var.project}-events-role"
  assume_role_policy = data.aws_iam_policy_document.events_assume[0].json
}

data "aws_iam_policy_document" "events" {
  count = var.create_orchestration ? 1 : 0

  statement {
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.batch[0].arn]
  }
}

resource "aws_iam_role_policy" "events" {
  count = var.create_orchestration ? 1 : 0

  name   = "${var.project}-events-start-sfn"
  role   = aws_iam_role.events[0].id
  policy = data.aws_iam_policy_document.events[0].json
}

resource "aws_cloudwatch_event_target" "batch_diario" {
  count = var.create_orchestration ? 1 : 0

  rule     = aws_cloudwatch_event_rule.batch_diario[0].name
  arn      = aws_sfn_state_machine.batch[0].arn
  role_arn = aws_iam_role.events[0].arn

  input = jsonencode({ gold_jobs = local.gold_job_names })
}
