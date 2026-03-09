// Ira Neo4j Schema v1
// Run in Neo4j Browser or via the seed script with --apply-schema.

CREATE CONSTRAINT company_name_unique IF NOT EXISTS
FOR (c:Company) REQUIRE c.name IS UNIQUE;

CREATE CONSTRAINT person_email_unique IF NOT EXISTS
FOR (p:Person) REQUIRE p.email IS UNIQUE;

CREATE CONSTRAINT machine_model_unique IF NOT EXISTS
FOR (m:Machine) REQUIRE m.model IS UNIQUE;

CREATE CONSTRAINT quote_id_unique IF NOT EXISTS
FOR (q:Quote) REQUIRE q.quote_id IS UNIQUE;

CREATE CONSTRAINT deal_id_unique IF NOT EXISTS
FOR (d:Deal) REQUIRE d.deal_id IS UNIQUE;

CREATE CONSTRAINT project_id_unique IF NOT EXISTS
FOR (p:Project) REQUIRE p.project_id IS UNIQUE;

CREATE CONSTRAINT milestone_id_unique IF NOT EXISTS
FOR (m:Milestone) REQUIRE m.milestone_id IS UNIQUE;

CREATE CONSTRAINT document_source_id_unique IF NOT EXISTS
FOR (d:Document) REQUIRE d.source_id IS UNIQUE;

CREATE CONSTRAINT fact_id_unique IF NOT EXISTS
FOR (f:Fact) REQUIRE f.fact_id IS UNIQUE;

CREATE CONSTRAINT correction_id_unique IF NOT EXISTS
FOR (c:Correction) REQUIRE c.correction_id IS UNIQUE;

CREATE INDEX company_region_idx IF NOT EXISTS
FOR (c:Company) ON (c.region);

CREATE INDEX company_industry_idx IF NOT EXISTS
FOR (c:Company) ON (c.industry);

CREATE INDEX deal_stage_idx IF NOT EXISTS
FOR (d:Deal) ON (d.stage);

CREATE INDEX project_status_idx IF NOT EXISTS
FOR (p:Project) ON (p.status);

CREATE INDEX doc_ingested_at_idx IF NOT EXISTS
FOR (d:Document) ON (d.ingested_at);

