# Ingress/DNS (spec 020 US4, FR-020): registro DNS del cliente → EIP de la VM;
# el TLS lo termina Caddy EN la VM (auto-HTTPS, cloud-init). DNS deriva del
# tenant.slug via product_domain (FR-014).

variable "prefix" { type = string }
variable "product_domain" { type = string }
variable "route53_zone_id" { type = string }
variable "public_ip" { type = string }

resource "aws_route53_record" "product" {
  zone_id = var.route53_zone_id
  name    = var.product_domain
  type    = "A"
  ttl     = 300
  records = [var.public_ip]
}

output "fqdn" { value = aws_route53_record.product.fqdn }
