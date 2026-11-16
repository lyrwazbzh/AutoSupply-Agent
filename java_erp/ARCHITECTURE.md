# Java ERP architecture

Java ERP is a modular monolith. MySQL transactions remain the consistency boundary;
Redis is limited to catalog query cache, login rate limiting and access ranking.

New business capabilities must use feature packages under `com.motorparts`, for example
`catalog`, `supplier.quotation`, `inventory.transaction`, `procurement`, `replenishment`,
`security` and `redis`. A feature package owns its controller, service, persistence model
and mapper. Cross-feature calls go through a service, not another feature's mapper.

The root `controller/service/service.impl/entity/mapper` packages contain the original
core CRUD slices. They are frozen: no new class may be added there. Existing slices are
moved into feature packages only when that slice receives a substantive change, so a
package-only big-bang refactor does not obscure business changes or destabilize MyBatis
scanning. The static architecture test records the current allowlist and prevents the two
styles from continuing to grow in parallel.

