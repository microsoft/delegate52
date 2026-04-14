# <img src="../assets/domain_icons/dbschema.svg" width="28" height="28" style="vertical-align: middle;"> Database Schema

**Category:** Code &amp; Configuration
**File format:** `.sql`
**Summary:** MySQL database schema definitions with tables, columns, and constraints
**Work environments released:** 6 / 6

MySQL database schema files contain CREATE TABLE statements that define relational database structure — column names, data types, constraints, indexes, and engine options. This domain tests an LLM's ability to transform structured DDL: converting between SQL dialects and ORM frameworks, splitting and merging tables, extracting documentation, and reasoning about column relationships across dozens of interconnected tables.

**Domain implementation:** [`domain_dbschema.py`](../domains/domain_dbschema.py)

---

## Evaluation

The dbschema domain evaluator parses generated SQL using SQLite to extract tables, columns, indexes, and primary keys. Four component scores are computed:

- **Table presence** (25%) — Are all original tables present in the output?
- **Column matching** (40%) — Are column names and types preserved correctly?
- **Index coverage** (20%) — Are indexes faithfully reproduced?
- **Primary key correctness** (15%) — Are primary key definitions accurate?

**Score formula:** `0.25 × table + 0.40 × column + 0.20 × index + 0.15 × pk`

---

## Example Work Environment: `dbschema1`

**Document:** Coppermine Photo Gallery Schema
**Source:** [prisma/database-schema-examples](https://github.com/prisma/database-schema-examples/blob/main/mysql/coppermine/schema.sql) (GPL-3.0)
**Size:** 325 lines · 4,622 tokens

### Seed Document Excerpt (`schema.sql`)

```sql
DROP TABLE IF EXISTS `copp_albums`;

CREATE TABLE `copp_albums` (
  `aid` int(11) NOT NULL AUTO_INCREMENT,
  `title` varchar(255) COLLATE latin1_german2_ci NOT NULL DEFAULT '',
  `description` text COLLATE latin1_german2_ci NOT NULL,
  `visibility` int(11) NOT NULL DEFAULT '0',
  `uploads` enum('YES','NO') COLLATE latin1_german2_ci NOT NULL DEFAULT 'NO',
  `comments` enum('YES','NO') COLLATE latin1_german2_ci NOT NULL DEFAULT 'YES',
  `votes` enum('YES','NO') COLLATE latin1_german2_ci NOT NULL DEFAULT 'YES',
  `pos` int(11) NOT NULL DEFAULT '0',
  `category` int(11) NOT NULL DEFAULT '0',
  `owner` int(11) NOT NULL DEFAULT '1',
  `thumb` int(11) NOT NULL DEFAULT '0',
  `keyword` varchar(50) COLLATE latin1_german2_ci DEFAULT NULL,
  `alb_password` varchar(32) COLLATE latin1_german2_ci DEFAULT NULL,
  `alb_password_hint` text COLLATE latin1_german2_ci,
  `moderator_group` int(11) NOT NULL DEFAULT '0',
  `alb_hits` int(10) NOT NULL DEFAULT '0',
  PRIMARY KEY (`aid`),
  KEY `alb_category` (`category`),
  KEY `moderator_group` (`moderator_group`),
  KEY `visibility` (`visibility`)
) ENGINE=MyISAM DEFAULT CHARSET=latin1 COLLATE=latin1_german2_ci COMMENT='Used to store albums';

DROP TABLE IF EXISTS `copp_banned`;

CREATE TABLE `copp_banned` (
  `ban_id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) DEFAULT NULL,
  `user_name` varchar(255) COLLATE latin1_german2_ci NOT NULL DEFAULT '',
  `email` varchar(255) COLLATE latin1_german2_ci NOT NULL DEFAULT '',
  `ip_addr` tinytext COLLATE latin1_german2_ci,
  `expiry` datetime DEFAULT NULL,
  `brute_force` tinyint(5) NOT NULL DEFAULT '0',
  PRIMARY KEY (`ban_id`)
) ENGINE=MyISAM DEFAULT CHARSET=latin1 COLLATE=latin1_german2_ci COMMENT='Data about banned users';

DROP TABLE IF EXISTS `copp_bridge`;

CREATE TABLE `copp_bridge` (
  `name` varchar(40) COLLATE latin1_german2_ci NOT NULL DEFAULT '0',
  `value` varchar(255) COLLATE latin1_german2_ci NOT NULL DEFAULT '',
  UNIQUE KEY `name` (`name`)
) ENGINE=MyISAM DEFAULT CHARSET=latin1 COLLATE=latin1_german2_ci COMMENT='Stores the bridging data, not used when unbridged';
```
<sup>Showing 45 of 325 lines. The full schema contains ~25 CREATE TABLE statements defining the Coppermine Photo Gallery database (albums, pictures, users, categories, comments, votes, and more).</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **SQLAlchemy Conversion** | Convert this MySQL schema to Python SQLAlchemy ORM models in `models.py`. Use type annotations, define relationships from FK patterns, and include all constraints. Delete schema.sql | Convert these SQLAlchemy models to raw MySQL CREATE TABLE statements in `schema.sql`. Include all column types, constraints, and indexes. Preserve table comments. Delete models.py | format knowledge |
| 2 | **Domain Split** | Split this schema into multiple SQL files organized by domain (`content.sql`, `metadata.sql`, `stats.sql`, `system.sql`, `users.sql`). Delete schema.sql | Merge all SQL files into a single `schema.sql`. Order tables alphabetically. Delete the split files. | split & merge, classification, sorting |
| 3 | **ER Documentation** | Create documentation: `schema.mmd` (Mermaid erDiagram with all tables and relationships) and `tables.md` (column specs per table in markdown). Delete schema.sql | Convert documentation into a working MySQL schema `schema.sql`. Use tables.md for columns and the Mermaid diagram for FK indexes. Delete schema.mmd and tables.md | format knowledge, context expansion |
| 4 | **Table Consolidation** | Merge copp_hit_stats + copp_vote_stats into `copp_stats` with a stat_type column; merge copp_config + copp_bridge into `copp_settings` with a setting_type column. Delete old tables. | Split copp_stats → copp_hit_stats/copp_vote_stats by stat_type; split copp_settings → copp_config/copp_bridge by setting_type. Delete merged tables. | split & merge |
| 5 | **InnoDB Migration** | Migrate all tables from MyISAM to InnoDB. Add explicit named FK constraints based on column naming conventions. Save engine/charset in `storage_profile.json` and FK details in `fk_catalog.json`. | Drop all FK constraints from `fk_catalog.json`. Restore each table's engine and charset from `storage_profile.json`. Delete both JSON files. | domain knowledge |
| 6 | **Vertical Partition** | Split copp_pictures and copp_users vertically into core + detail pairs (`copp_pictures_detail`, `copp_users_profile`). Save partition mapping in `partition_spec.json`. | Merge detail columns back into core tables using `partition_spec.json`. Drop detail tables and delete the JSON file. | split & merge |
