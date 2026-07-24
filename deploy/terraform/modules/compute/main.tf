# Cómputo v1 (spec 020 US4, FR-018): VM + docker compose por cloud-init desde
# las imágenes PINNEADAS de US1 y el perfil renderizado de US3. El roadmap v2
# (k3s+Helm+Zarf) reemplaza este módulo sin tocar el resto (ver research).

variable "prefix" { type = string }
variable "subnet_id" { type = string }
variable "app_sg_id" { type = string }
variable "instance_type" { type = string }
variable "product_domain" { type = string }
variable "backend_image" { type = string }
variable "frontend_image" { type = string }
variable "litellm_image" { type = string }
variable "nlp_analyzer_image" { type = string }
variable "image_source" { type = string }
variable "profile_path" { type = string }
variable "postgres_host" { type = string }
variable "postgres_db" { type = string }
variable "postgres_user" { type = string }
variable "postgres_password" {
  type      = string
  sensitive = true
}
variable "redis_host" { type = string }
variable "litellm_master_key" {
  type      = string
  sensitive = true
}
variable "fernet_secret_key" {
  type      = string
  sensitive = true
}
variable "jwt_secret_key" {
  type      = string
  sensitive = true
}

data "aws_ami" "debian" {
  most_recent = true
  owners      = ["136693071363"] # Debian oficial
  filter {
    name   = "name"
    values = ["debian-12-amd64-*"]
  }
}

resource "aws_instance" "this" {
  ami                    = data.aws_ami.debian.id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [var.app_sg_id]

  user_data = templatefile("${path.module}/templates/cloud-init.yaml.tpl", {
    product_domain     = var.product_domain
    backend_image      = var.backend_image
    frontend_image     = var.frontend_image
    litellm_image      = var.litellm_image
    nlp_analyzer_image = var.nlp_analyzer_image
    image_source       = var.image_source
    instance_env       = file("${var.profile_path}/instance.env")
    brand_json         = file("${var.profile_path}/brand.json")
    litellm_config     = file("${var.profile_path}/config.yaml")
    compose_prod       = file("${path.module}/../../../docker/compose.prod.yml")
    postgres_host      = var.postgres_host
    postgres_db        = var.postgres_db
    postgres_user      = var.postgres_user
    postgres_password  = var.postgres_password
    redis_host         = var.redis_host
    litellm_master_key = var.litellm_master_key
    fernet_secret_key  = var.fernet_secret_key
    jwt_secret_key     = var.jwt_secret_key
  })

  root_block_device {
    volume_size = 30
    encrypted   = true
  }

  tags = { Name = "${var.prefix}-app" }
}

resource "aws_eip" "app" {
  domain   = "vpc"
  instance = aws_instance.this.id
  tags     = { Name = "${var.prefix}-app-eip" }
}

output "instance_id" { value = aws_instance.this.id }
output "public_ip" { value = aws_eip.app.public_ip }
