from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import sqlite3
import os, re, ujson as json


def mysql_to_sqlite(sql):
    # Remove MySQL-specific syntax to make it SQLite-compatible

    # Remove SET statements (SET FOREIGN_KEY_CHECKS, SET SESSION, SET NAMES, etc.)
    sql = re.sub(r'^\s*SET\s+[^;]*;', '', sql, flags=re.IGNORECASE | re.MULTILINE)
    # Remove MySQL conditional comments: /*!40101 SET ... */;
    sql = re.sub(r'/\*!\d+\s+[^*]*\*/', '', sql)
    # Remove # comments (MySQL-style) — only at start of line to avoid stripping inside URLs
    sql = re.sub(r'^\s*#[^\n]*', '', sql, flags=re.MULTILINE)
    # Remove INSERT/UPDATE/DELETE statements (we only care about schema structure)
    sql = re.sub(r'^\s*INSERT\s+INTO\s+[^;]*;', '', sql, flags=re.IGNORECASE | re.MULTILINE)
    sql = re.sub(r'^\s*UPDATE\s+[^;]*;', '', sql, flags=re.IGNORECASE | re.MULTILINE)
    sql = re.sub(r'^\s*DELETE\s+[^;]*;', '', sql, flags=re.IGNORECASE | re.MULTILINE)

    sql = re.sub(r'ENGINE\s*=\s*\w+', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'DEFAULT\s+CHARSET\s*=\s*\w+', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'ROW_FORMAT\s*=\s*\w+', '', sql, flags=re.IGNORECASE)
    # Column-level or table-level CHARACTER SET ... COLLATE ... (optionally preceded by DEFAULT)
    sql = re.sub(r'(?:DEFAULT\s+)?CHARACTER\s+SET\s+\w+(\s+COLLATE\s+\w+)?', '', sql, flags=re.IGNORECASE)
    # Table-level or standalone COLLATE
    sql = re.sub(r'COLLATE\s*=?\s*\w+', '', sql, flags=re.IGNORECASE)
    # Standalone COLLATION placeholder with optional =value (e.g., COLLATION=COLLATION)
    sql = re.sub(r'\bCOLLATION\b\s*=?\s*\w*', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'AUTO_INCREMENT\s*=\s*\d+', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'AUTO_INCREMENT', '', sql, flags=re.IGNORECASE)
    # COMMENT = 'text' or COMMENT = "text"
    sql = re.sub(r'COMMENT\s*=\s*\'[^\']*\'', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'COMMENT\s*=\s*"[^"]*"', '', sql, flags=re.IGNORECASE)
    # COMMENT 'text' (without =, appears on columns; handle SQL-style '' escape)
    sql = re.sub(r"COMMENT\s+'(?:[^']|'')*'", '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'COMMENT\s+"(?:[^"]|"")*"', '', sql, flags=re.IGNORECASE)
    # ON UPDATE CURRENT_TIMESTAMP (with optional precision)
    sql = re.sub(r'ON\s+UPDATE\s+CURRENT_TIMESTAMP(\(\d*\))?', '', sql, flags=re.IGNORECASE)
    # timestamp/datetime with precision: timestamp(6) -> timestamp
    sql = re.sub(r'\b(timestamp|datetime)\s*\(\d+\)', r'\1', sql, flags=re.IGNORECASE)
    # CURRENT_TIMESTAMP(6) -> CURRENT_TIMESTAMP
    sql = re.sub(r'CURRENT_TIMESTAMP\s*\(\d*\)', 'CURRENT_TIMESTAMP', sql, flags=re.IGNORECASE)

    # Remove general block comments (but not conditional /*!...*/ which are already handled)
    sql = re.sub(r'/\*(?!!)[^*]*(?:\*(?!/)[^*]*)*\*/', '', sql)
    # Remove MySQL table options: MAX_ROWS, AVG_ROW_LENGTH, PACK_KEYS, CHECKSUM, DELAY_KEY_WRITE, MIN_ROWS
    sql = re.sub(r'MAX_ROWS\s*=\s*\d+', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'AVG_ROW_LENGTH\s*=\s*\d+', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'PACK_KEYS\s*=\s*\d+', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'CHECKSUM\s*=\s*\d+', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'DELAY_KEY_WRITE\s*=\s*\d+', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'MIN_ROWS\s*=\s*\d+', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r"`", '"', sql)  # backticks to double quotes
    sql = re.sub(r"enum\s*\([^)]+\)", 'TEXT', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bset\s*\([^)]+\)', 'TEXT', sql, flags=re.IGNORECASE)  # MySQL SET type
    # Type conversions: more specific types MUST come before generic int
    sql = re.sub(r'\btinyint\b(\(\d+\))?', 'INTEGER', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bsmallint\b(\(\d+\))?', 'INTEGER', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bmediumint\b(\(\d+\))?', 'INTEGER', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bbigint\b(\(\d+\))?', 'INTEGER', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bint\b(\(\d+\))?', 'INTEGER', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bunsigned\b', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\btinytext\b', 'TEXT', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bmediumtext\b', 'TEXT', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\blongtext\b', 'TEXT', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bmediumblob\b', 'BLOB', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\blongblob\b', 'BLOB', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\btinyblob\b', 'BLOB', sql, flags=re.IGNORECASE)
    # binary(N) as a data type -> BLOB; standalone BINARY (column attribute) -> remove
    sql = re.sub(r'\bbinary\s*\(\d+\)', 'BLOB', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bbinary\b', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bdouble\b', 'REAL', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bjson\b', 'TEXT', sql, flags=re.IGNORECASE)
    # Remove GENERATED ALWAYS AS (...) VIRTUAL/STORED — use iterative matching for nested parens
    def _remove_generated_cols(s):
        pattern = re.compile(r'GENERATED\s+ALWAYS\s+AS\s*\(', re.IGNORECASE)
        while True:
            m = pattern.search(s)
            if not m:
                break
            # Find matching close paren
            depth = 1
            i = m.end()
            while i < len(s) and depth > 0:
                if s[i] == '(':
                    depth += 1
                elif s[i] == ')':
                    depth -= 1
                i += 1
            # Remove through VIRTUAL/STORED keyword
            rest = s[i:]
            vm = re.match(r'\s*(?:VIRTUAL|STORED)', rest, re.IGNORECASE)
            end = i + vm.end() if vm else i
            s = s[:m.start()] + s[end:]
        return s
    sql = _remove_generated_cols(sql)
    # Remove CONSTRAINT ... FOREIGN KEY ... REFERENCES ... (with optional ON DELETE/UPDATE clauses)
    sql = re.sub(r',?\s*CONSTRAINT\s+"[^"]+"\s+FOREIGN\s+KEY\s*\([^)]+\)\s*REFERENCES\s+"[^"]+"\s*\([^)]+\)(\s+ON\s+(DELETE|UPDATE)\s+(CASCADE|SET\s+NULL|SET\s+DEFAULT|RESTRICT|NO\s+ACTION))*', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r',?\s*CONSTRAINT\s+\w+\s+FOREIGN\s+KEY\s*\([^)]+\)\s*REFERENCES\s+\w+\s*\([^)]+\)(\s+ON\s+(DELETE|UPDATE)\s+(CASCADE|SET\s+NULL|SET\s+DEFAULT|RESTRICT|NO\s+ACTION))*', '', sql, flags=re.IGNORECASE)
    # Standalone FOREIGN KEY (no CONSTRAINT name)
    sql = re.sub(r',?\s*FOREIGN\s+KEY\s*\([^)]+\)\s*REFERENCES\s+"[^"]+"\s*\([^)]+\)(\s+ON\s+(DELETE|UPDATE)\s+(CASCADE|SET\s+NULL|SET\s+DEFAULT|RESTRICT|NO\s+ACTION))*', '', sql, flags=re.IGNORECASE)
    # Remove KEY definitions that aren't PRIMARY or UNIQUE (SQLite doesn't support them inline)
    sql = re.sub(r',\s*KEY\s+"[^"]+"\s*\([^)]+\)', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r',\s*KEY\s+\w+\s*\([^)]+\)', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r',\s*KEY\s*\([^)]+\)', '', sql, flags=re.IGNORECASE)
    # Remove inline INDEX definitions: INDEX "name" ("cols") or INDEX name ("cols")
    sql = re.sub(r',\s*INDEX\s+"[^"]+"\s*\([^)]+\)', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r',\s*INDEX\s+\w+\s*\([^)]+\)', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r',\s*INDEX\s*\([^)]+\)', '', sql, flags=re.IGNORECASE)
    # Remove UNIQUE INDEX definitions (inline)
    sql = re.sub(r',\s*UNIQUE\s+INDEX\s+"[^"]+"\s*\([^)]+\)', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r',\s*UNIQUE\s+INDEX\s+\w+\s*\([^)]+\)', '', sql, flags=re.IGNORECASE)
    # Remove FULLTEXT KEY/INDEX definitions
    sql = re.sub(r',\s*FULLTEXT\s+(?:KEY|INDEX)\s+"[^"]+"\s*\([^)]+\)', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r',\s*FULLTEXT\s+(?:KEY|INDEX)\s+\w+\s*\([^)]+\)', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r',\s*FULLTEXT\s*\([^)]+\)', '', sql, flags=re.IGNORECASE)
    # Convert UNIQUE KEY (cols) (no name) to UNIQUE (cols)
    sql = re.sub(r'UNIQUE\s+KEY\s*(\([^)]+\))', r'UNIQUE \1', sql, flags=re.IGNORECASE)
    # Convert UNIQUE KEY "name" (cols) to UNIQUE (cols)
    sql = re.sub(r'UNIQUE\s+KEY\s+"[^"]+"\s*(\([^)]+\))', r'UNIQUE \1', sql, flags=re.IGNORECASE)
    sql = re.sub(r'UNIQUE\s+KEY\s+\w+\s*(\([^)]+\))', r'UNIQUE \1', sql, flags=re.IGNORECASE)
    # Convert named UNIQUE "name" (cols) (no KEY keyword) to UNIQUE (cols)
    sql = re.sub(r'UNIQUE\s+"[^"]+"\s*(\([^)]+\))', r'UNIQUE \1', sql, flags=re.IGNORECASE)
    # Convert named PRIMARY KEY "name" (cols) to PRIMARY KEY (cols)
    sql = re.sub(r'PRIMARY\s+KEY\s+"[^"]+"\s*(\([^)]+\))', r'PRIMARY KEY \1', sql, flags=re.IGNORECASE)
    sql = re.sub(r'PRIMARY\s+KEY\s+(?![\("])(\w+)\s*(\([^)]+\))', r'PRIMARY KEY \2', sql, flags=re.IGNORECASE)
    # Strip MySQL index prefix lengths: "col"(255) -> "col" in constraint definitions
    sql = re.sub(r'("[^"]+")\s*\(\d+\)', r'\1', sql)
    # Clean up residual table-option artifacts between closing ) and ;
    # Handles leftover words like bare collation names, DEFAULT, = etc.
    sql = re.sub(r'\)[ \t]+\w[\w \t]*;', ');', sql)
    sql = re.sub(r'\)\s*=\s*;', ');', sql, flags=re.IGNORECASE)
    return sql


def extract_schema_from_sql(sql):
    """Extract schema from SQL, tolerating parse errors for individual statements."""
    adapted_sql = mysql_to_sqlite(sql)
    
    # Try executescript first (handles most cases)
    conn = sqlite3.connect(':memory:')
    try:
        conn.executescript(adapted_sql)
    except sqlite3.Error:
        conn.close()
        # Fall back to parsing individual CREATE TABLE statements
        conn = sqlite3.connect(':memory:')
        # Extract CREATE TABLE blocks using regex
        create_stmts = re.findall(
            r'((?:DROP\s+TABLE\s+IF\s+EXISTS\s+[^;]+;\s*)?CREATE\s+TABLE\s+[^;]+;)',
            adapted_sql, flags=re.IGNORECASE | re.DOTALL
        )
        for stmt in create_stmts:
            try:
                conn.executescript(stmt)
            except sqlite3.Error:
                continue  # Skip tables that can't be parsed
    
    tables = {}
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    for (table_name,) in cursor.fetchall():
        # Get columns: (cid, name, type, notnull, default_value, pk)
        columns = {}
        for row in conn.execute(f'PRAGMA table_info("{table_name}")'):
            cid, name, col_type, notnull, default_val, pk = row
            columns[name.lower()] = {"name": name.lower(), "type": col_type.upper() if col_type else "", "notnull": bool(notnull), "default": default_val, "pk": pk > 0}
        
        # Get indexes
        indexes = []
        for idx_row in conn.execute(f'PRAGMA index_list("{table_name}")'):
            idx_name = idx_row[1]
            idx_unique = bool(idx_row[2])
            idx_cols = []
            for col_row in conn.execute(f'PRAGMA index_info("{idx_name}")'):
                col_name = col_row[2]
                if col_name is not None:
                    idx_cols.append(col_name.lower())
            if idx_cols:
                indexes.append({"name": idx_name, "unique": idx_unique, "columns": frozenset(idx_cols)})
        
        # Get primary key columns
        pk_cols = [c["name"] for c in columns.values() if c["pk"]]
        
        tables[table_name.lower()] = {"columns": columns, "indexes": indexes, "pk_cols": pk_cols}
    
    conn.close()
    return tables, None


def normalize_sql_type(col_type):
    col_type = col_type.upper().strip()
    # Group equivalent types
    if col_type in ('INT', 'INTEGER', 'TINYINT', 'SMALLINT', 'MEDIUMINT', 'BIGINT'):
        return 'INTEGER'
    if col_type in ('TEXT', 'TINYTEXT', 'MEDIUMTEXT', 'LONGTEXT', 'CLOB'):
        return 'TEXT'
    if col_type.startswith('VARCHAR') or col_type.startswith('CHAR'):
        return 'TEXT'
    if col_type in ('REAL', 'FLOAT', 'DOUBLE'):
        return 'REAL'
    if col_type in ('BLOB',):
        return 'BLOB'
    return col_type


def compute_table_presence_score(ref_tables, gen_tables):
    ref_names = set(ref_tables.keys())
    gen_names = set(gen_tables.keys())
    if not ref_names and not gen_names:
        return 1.0
    if not ref_names or not gen_names:
        return 0.0
    return len(ref_names & gen_names) / len(ref_names | gen_names)


def compute_column_pair_score(ref_col, gen_col):
    # Type match (normalized)
    ref_type = normalize_sql_type(ref_col["type"])
    gen_type = normalize_sql_type(gen_col["type"])
    type_score = 1.0 if ref_type == gen_type else 0.5
    
    # Notnull match
    notnull_score = 1.0 if ref_col["notnull"] == gen_col["notnull"] else 0.7
    
    # PK match
    pk_score = 1.0 if ref_col["pk"] == gen_col["pk"] else 0.5
    
    # Default match (lenient - just check if both have or both don't have)
    ref_has_default = ref_col["default"] is not None
    gen_has_default = gen_col["default"] is not None
    default_score = 1.0 if ref_has_default == gen_has_default else 0.8
    
    return type_score * 0.4 + notnull_score * 0.2 + pk_score * 0.3 + default_score * 0.1


def compute_table_column_score(ref_cols, gen_cols):
    if not ref_cols and not gen_cols:
        return 1.0
    if not ref_cols:
        return 0.0
    
    ref_names = set(ref_cols.keys())
    gen_names = set(gen_cols.keys())
    
    matched_names = ref_names & gen_names
    missing_names = ref_names - gen_names
    extra_names = gen_names - ref_names
    
    # Score matched columns
    matched_scores = []
    for name in matched_names:
        matched_scores.append(compute_column_pair_score(ref_cols[name], gen_cols[name]))
    
    total_matched_score = sum(matched_scores)
    # Missing columns contribute 0, extra columns have smaller penalty
    denominator = len(ref_cols) + 0.3 * len(extra_names)
    
    return total_matched_score / denominator if denominator > 0 else 0.0


def compute_column_score(ref_tables, gen_tables):
    common_tables = set(ref_tables.keys()) & set(gen_tables.keys())
    if not common_tables:
        return 0.0
    
    scores = []
    for tname in common_tables:
        score = compute_table_column_score(ref_tables[tname]["columns"], gen_tables[tname]["columns"])
        scores.append(score)
    
    return sum(scores) / len(scores)


def compute_index_score(ref_tables, gen_tables):
    common_tables = set(ref_tables.keys()) & set(gen_tables.keys())
    if not common_tables:
        return 0.0
    
    scores = []
    for tname in common_tables:
        ref_idx_sets = {idx["columns"] for idx in ref_tables[tname]["indexes"]}
        gen_idx_sets = {idx["columns"] for idx in gen_tables[tname]["indexes"]}
        
        if not ref_idx_sets and not gen_idx_sets:
            scores.append(1.0)
        elif not ref_idx_sets or not gen_idx_sets:
            scores.append(0.0)
        else:
            scores.append(len(ref_idx_sets & gen_idx_sets) / len(ref_idx_sets | gen_idx_sets))
    
    return sum(scores) / len(scores)


def compute_pk_score(ref_tables, gen_tables):
    common_tables = set(ref_tables.keys()) & set(gen_tables.keys())
    if not common_tables:
        return 0.0
    
    matches = 0
    for tname in common_tables:
        ref_pk = set(ref_tables[tname]["pk_cols"])
        gen_pk = set(gen_tables[tname]["pk_cols"])
        if ref_pk == gen_pk:
            matches += 1
    
    return matches / len(common_tables)


class DomainDbschema(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "dbschema"
        self.summary = "MySQL database schema definitions with tables, columns, and constraints"
        self.description = "SQL database schemas"
        self.file_format = [".sql"]
        self.domain_parser = "sqlite3"
        self.category = "code"
    
    def get_sql_content(self, context):
        sql_content = ""
        for filename, content in context.items():
            if filename.endswith('.sql'):
                sql_content += content + "\n"
        return sql_content
    
    def parse_context(self, context):
        sql = self.get_sql_content(context)
        tables, error = extract_schema_from_sql(sql)
        return {"tables": tables if tables else {}, "error": error}
    
    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        tables = parsed["tables"]
        if parsed["error"] or not tables:
            return {"Tables": 0}
        num_columns = sum(len(t.get('columns', [])) for t in tables.values())
        num_indexes = sum(len(t.get('indexes', [])) for t in tables.values())
        return {
            "Tables": len(tables),
            "Columns": num_columns,
            "Indexes": num_indexes,
        }
    
    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        if target_state["state_id"] != "basic_state":
            return {}
        
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)
        
        start_state_id = sample["start_state"]
        start_state = [state for state in sample["states"] if state["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))
        
        ref_parsed = self.parse_context(reference_context)
        gen_parsed = self.parse_context(generated_context)
        
        ref_tables = ref_parsed["tables"]
        gen_tables = gen_parsed["tables"]
        
        if ref_parsed["error"]:
            return {"error": "ref_sql_parse_error", "details": ref_parsed["error"], "score": 0.0}
        if gen_parsed["error"]:
            return {"error": "gen_sql_parse_error", "details": gen_parsed["error"], "score": 0.0}
        
        if debug:
            print(f"Parsed {len(ref_tables)} ref tables, {len(gen_tables)} gen tables")
            print(f"Ref tables: {list(ref_tables.keys())[:5]}...")
            print(f"Gen tables: {list(gen_tables.keys())[:5]}...")
        
        # Compute component scores
        presence_score = compute_table_presence_score(ref_tables, gen_tables)
        column_score = compute_column_score(ref_tables, gen_tables)
        index_score = compute_index_score(ref_tables, gen_tables)
        pk_score = compute_pk_score(ref_tables, gen_tables)
        
        # Weighted aggregate
        score = 0.25 * presence_score + 0.40 * column_score + 0.20 * index_score + 0.15 * pk_score
        
        eval_obj = {
            "score": score,
            "table_presence_score": presence_score,
            "column_score": column_score,
            "index_score": index_score,
            "pk_score": pk_score,
            "ref_table_count": len(ref_tables),
            "gen_table_count": len(gen_tables),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
