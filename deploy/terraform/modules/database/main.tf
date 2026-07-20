# Postgres GESTIONADO (spec 020 US4, FR-016): RDS en subredes privadas; la app
# entra por referencia de SG. El backend/motor lo consumen por swap POSTGRES_*
# (adiós pgdata efímero del compose de dev).

variable "prefix" { type = string }
variable "subnet_ids" { type = list(string) }
variable "vpc_id" { type = string }
variable "app_sg_id" { type = string }
variable "instance_class" { type = string }
variable "postgres_password" {
  type      = string
  sensitive = true
}

resource "aws_db_subnet_group" "this" {
  name       = "${var.prefix}-db"
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "db" {
  name   = "${var.prefix}-db"
  vpc_id = var.vpc_id
  ingress {
    description     = "postgres desde la app"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.app_sg_id]
  }
}

resource "aws_db_instance" "this" {
  identifier                = "${var.prefix}-pg"
  engine                    = "postgres"
  engine_version            = "16"
  instance_class            = var.instance_class
  allocated_storage         = 20
  storage_encrypted         = true
  db_name                   = "basa_gateway"
  username                  = "basa_admin"
  password                  = var.postgres_password
  db_subnet_group_name      = aws_db_subnet_group.this.name
  vpc_security_group_ids    = [aws_security_group.db.id]
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.prefix}-pg-final"
  backup_retention_period   = 7
  deletion_protection       = true
}

output "endpoint" { value = aws_db_instance.this.address }
output "db_name" { value = aws_db_instance.this.db_name }
output "username" { value = aws_db_instance.this.username }
