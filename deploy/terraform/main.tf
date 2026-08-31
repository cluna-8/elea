# Root del módulo (spec 020 US4): compone los submódulos por recurso. Todo el
# naming deriva de tenant_slug (Principio III: un cliente = un workspace + un
# prefijo de recursos, sin colisión con otros clientes del distribuidor).

locals {
  prefix = "sentinel-${var.tenant_slug}"
}

module "network" {
  source = "./modules/network"
  prefix = local.prefix
}

module "secrets" {
  source = "./modules/secrets"
}

module "database" {
  source            = "./modules/database"
  prefix            = local.prefix
  subnet_ids        = module.network.private_subnet_ids
  vpc_id            = module.network.vpc_id
  app_sg_id         = module.network.app_sg_id
  instance_class    = var.db_instance_class
  postgres_password = module.secrets.postgres_password
}

module "cache" {
  source     = "./modules/cache"
  prefix     = local.prefix
  subnet_ids = module.network.private_subnet_ids
  vpc_id     = module.network.vpc_id
  app_sg_id  = module.network.app_sg_id
  node_type  = var.cache_node_type
}

module "compute" {
  source             = "./modules/compute"
  prefix             = local.prefix
  subnet_id          = module.network.public_subnet_ids[0]
  app_sg_id          = module.network.app_sg_id
  instance_type      = var.instance_type
  product_domain     = var.product_domain
  backend_image      = var.backend_image
  frontend_image     = var.frontend_image
  litellm_image      = var.litellm_image
  nlp_analyzer_image = var.nlp_analyzer_image
  image_source       = var.image_source
  profile_path       = var.profile_path
  postgres_host      = module.database.endpoint
  postgres_db        = module.database.db_name
  postgres_user      = module.database.username
  postgres_password  = module.secrets.postgres_password
  redis_host         = module.cache.endpoint
  litellm_master_key = module.secrets.litellm_master_key
  fernet_secret_key  = module.secrets.fernet_secret_key
  jwt_secret_key     = module.secrets.jwt_secret_key
}

module "ingress" {
  source          = "./modules/ingress"
  prefix          = local.prefix
  product_domain  = var.product_domain
  route53_zone_id = var.route53_zone_id
  public_ip       = module.compute.public_ip
}

# Guard de residencia EU (FR-021): el apply FALLA fuera de EU salvo override
# explícito y auditable (allow_non_eu=true). Vive como precondition porque la
# validation de variables no puede cruzar variables en tofu 1.8.
resource "terraform_data" "eu_region_guard" {
  lifecycle {
    precondition {
      condition     = var.allow_non_eu || can(regex("^eu-", var.region))
      error_message = "Región '${var.region}' fuera de EU (FR-021, residencia GDPR). Si es intencional: allow_non_eu=true."
    }
  }
}
