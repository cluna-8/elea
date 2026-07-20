# Redis GESTIONADO (spec 020 US4, FR-017): ElastiCache en privadas; swap REDIS_*.

variable "prefix" { type = string }
variable "subnet_ids" { type = list(string) }
variable "vpc_id" { type = string }
variable "app_sg_id" { type = string }
variable "node_type" { type = string }

resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.prefix}-redis"
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "redis" {
  name   = "${var.prefix}-redis"
  vpc_id = var.vpc_id
  ingress {
    description     = "redis desde la app"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [var.app_sg_id]
  }
}

resource "aws_elasticache_cluster" "this" {
  cluster_id         = "${var.prefix}-redis"
  engine             = "redis"
  node_type          = var.node_type
  num_cache_nodes    = 1
  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.redis.id]
}

output "endpoint" { value = aws_elasticache_cluster.this.cache_nodes[0].address }
