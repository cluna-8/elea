"""Núcleo de licenciamiento offline (spec 021 — Licensing & Seat Enforcement).

Verificación Ed25519 LOCAL del artefacto de licencia (.lic) + entitlement en
memoria + gate de seats en la creación. El producto sólo VERIFICA licencias
(la privada de firma vive del lado de Sentinel, FR-002); todo corre sin ninguna
llamada de red (FR-004: cajas on-prem/VPN sin egress).
"""
