# -*- coding: utf-8 -*-
"""
把包含 CREATE TABLE 语句的 SQL 文件，转换成 ER 图（SVG）。

功能：
    - 主键列在最上面，标记 (PK)
    - 外键列在主键下面，标记 (FK)
    - 其他列在最后
    - 如果某个外键列参与 UNIQUE 约束：
        * 箭头标签为两行：
            col → RefTable.ref_col
            UNIQUE(col) 或 UNIQUE(col1, col2, ...)
    - 输出文件名使用不带后缀的 basename，例如：er_diagram → er_diagram.svg

使用方式：
    1. 在 CONFIG 部分修改 INPUT_SQL 和 OUTPUT_BASENAME
    2. 确保已安装：
         pip install graphviz sqlparse
       并且系统安装了 Graphviz 程序（dot.exe 在 PATH 里）
    3. 运行：python sql_to_svg.py
"""

import re
import sys
from graphviz import Digraph
import sqlparse

# ==========================
# CONFIG：在这里改就行
# ==========================
INPUT_SQL = "schema.sql"   # 你的 SQL schema 文件路径
OUTPUT_BASENAME = "er_diagram"   # 不带扩展名，最终会生成 er_diagram.svg


# ==========================
# 工具函数：清理 SQL 注释
# ==========================
def strip_sql_comments(sql_text: str) -> str:
    """
    去除 SQL 中的行尾注释和块注释，避免干扰解析。

    - 行尾注释：-- comment
    - 块注释：  /* ... */
    """
    # 去除行尾 -- 注释
    sql_text = re.sub(r'--.*$', '', sql_text, flags=re.MULTILINE)
    # 去除 /* ... */ 块注释
    sql_text = re.sub(r'/\*.*?\*/', '', sql_text, flags=re.DOTALL)
    return sql_text


# ==========================
# 解析函数
# ==========================
def parse_sql_schema(sql_text):
    """
    粗略解析 SQL 里的 CREATE TABLE 语句，提取：
    - tables: {
        table_name: {
            "columns":  set,                          # 所有列名
            "pk":       set,                          # 主键列
            "fks":      [(col, ref_table, ref_col)],  # 外键
            "uniques":  [set(col_names), ...]         # 唯一约束涉及的列集合
        }
      }

    支持：
        * 列级 PRIMARY KEY：id INTEGER PRIMARY KEY
        * 表级 PRIMARY KEY：PRIMARY KEY(id, ...)
        * 列级 FOREIGN KEY：col INTEGER REFERENCES Other(id)
        * 表级 FOREIGN KEY：FOREIGN KEY(col) REFERENCES Other(id)
        * UNIQUE 约束：列级 UNIQUE、表级 UNIQUE(...)、CONSTRAINT ... UNIQUE(...)
    """
    tables = {}

    # 去注释
    sql_text = strip_sql_comments(sql_text)

    # 用 sqlparse 拆分语句
    statements = sqlparse.split(sql_text)

    create_table_re = re.compile(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([`\"\[]?)(\w+)\1\s*\((.*)\)",
        re.IGNORECASE | re.DOTALL
    )
    create_table_simple_re = re.compile(
        r"CREATE\s+TABLE\s+([`\"\[]?)(\w+)\1\s*\((.*)\)",
        re.IGNORECASE | re.DOTALL
    )

    for stmt in statements:
        s = stmt.strip().strip(";")
        if not s:
            continue

        m = create_table_re.search(s) or create_table_simple_re.search(s)
        if not m:
            continue

        table_name = m.group(2)
        body = m.group(3)

        # 按逗号拆分列/约束，注意括号深度
        parts = []
        current = []
        depth = 0
        for ch in body:
            if ch == "(":
                depth += 1
                current.append(ch)
            elif ch == ")":
                depth -= 1
                current.append(ch)
            elif ch == "," and depth == 0:
                part = "".join(current).strip()
                if part:
                    parts.append(part)
                current = []
            else:
                current.append(ch)
        if current:
            part = "".join(current).strip()
            if part:
                parts.append(part)

        tables[table_name] = {
            "columns": set(),
            "pk": set(),
            "fks": [],        # (col, ref_table, ref_col)
            "uniques": []     # [set(col_names), ...]
        }

        for part in parts:
            p = part.strip()
            if not p:
                continue
            up = p.upper().lstrip()

            # ---------- 表级约束：PRIMARY KEY ----------
            if up.startswith("PRIMARY KEY"):
                # PRIMARY KEY(col1, col2, ...)
                if "(" in p and ")" in p:
                    cols_str = p[p.find("(") + 1:p.rfind(")")]
                    cols = [c.strip(" `\"[]") for c in cols_str.split(",") if c.strip()]
                    tables[table_name]["pk"].update(cols)
                continue

            # ---------- 表级约束：FOREIGN KEY ----------
            if up.startswith("FOREIGN KEY"):
                # FOREIGN KEY (col1, col2) REFERENCES Other(ref1, ref2)
                if "(" in p and ")" in p:
                    fk_cols_str = p[p.find("(") + 1:p.find(")")]
                    fk_cols = [c.strip(" `\"[]") for c in fk_cols_str.split(",") if c.strip()]
                else:
                    fk_cols = []

                ref_match = re.search(
                    r"REFERENCES\s+([`\"\[]?)(\w+)\1\s*\(([^)]+)\)",
                    p,
                    flags=re.IGNORECASE
                )
                if ref_match:
                    ref_table = ref_match.group(2)
                    ref_cols_str = ref_match.group(3)
                    ref_cols = [c.strip(" `\"[]") for c in ref_cols_str.split(",") if c.strip()]
                    for lc, rc in zip(fk_cols, ref_cols):
                        tables[table_name]["fks"].append((lc, ref_table, rc))
                continue

            # ---------- 表级 UNIQUE(...) ----------
            if up.startswith("UNIQUE"):
                # UNIQUE(col1, col2, ...)
                if "(" in p and ")" in p:
                    cols_str = p[p.find("(") + 1:p.rfind(")")]
                    cols = [c.strip(" `\"[]") for c in cols_str.split(",") if c.strip()]
                    if cols:
                        tables[table_name]["uniques"].append(set(cols))
                continue

            # ---------- 表级 CONSTRAINT ... UNIQUE(...) 或 CHECK ----------
            if up.startswith("CONSTRAINT"):
                # CONSTRAINT uq_xxx UNIQUE (layer_id, ...)
                if "UNIQUE" in up:
                    m_uq = re.search(
                        r"UNIQUE\s*\(([^)]+)\)",
                        p,
                        flags=re.IGNORECASE
                    )
                    if m_uq:
                        cols_str = m_uq.group(1)
                        cols = [c.strip(" `\"[]") for c in cols_str.split(",") if c.strip()]
                        if cols:
                            tables[table_name]["uniques"].append(set(cols))
                # 不管有没有 UNIQUE，CONSTRAINT 这行肯定不是列定义
                continue

            if up.startswith("CHECK"):
                # CHECK (...) 也不是列定义
                continue

            # ---------- 列定义 ----------
            tokens = p.split()
            if not tokens:
                continue

            first_token = tokens[0].strip("`\"[]")
            first_up = first_token.upper()

            # 极端情况再防一手
            if first_up in ("CONSTRAINT", "UNIQUE", "CHECK"):
                continue

            col_name = first_token
            tables[table_name]["columns"].add(col_name)

            # 列级 PRIMARY KEY
            if "PRIMARY KEY" in up:
                tables[table_name]["pk"].add(col_name)

            # 列级 UNIQUE：col ... UNIQUE
            if "UNIQUE" in up:
                tables[table_name]["uniques"].append({col_name})

            # 列级 FOREIGN KEY：col INTEGER REFERENCES Other(id)
            ref_match_inline = re.search(
                r"REFERENCES\s+([`\"\[]?)(\w+)\1\s*\(([^)]+)\)",
                p,
                flags=re.IGNORECASE
            )
            if ref_match_inline:
                ref_table = ref_match_inline.group(2)
                ref_col_str = ref_match_inline.group(3)
                ref_cols = [c.strip(" `\"[]") for c in ref_col_str.split(",") if c.strip()]
                ref_col = ref_cols[0] if ref_cols else "id"
                tables[table_name]["fks"].append((col_name, ref_table, ref_col))

    return tables


# ==========================
# 画图函数
# ==========================
def build_er_graph(tables, graph_name="ER_Diagram"):
    """
    根据解析出的 tables 结构，用 Graphviz 画 ER 图。

    - 每个表一个节点（record 形式）
      * 主键列在最上面，显示 "name (PK)"
      * 外键列在主键下面，显示 "name (FK)"
      * 其他列在最后
    - 外键边：
      * label 默认："col → RefTable.ref_col"
      * 若该 col 参与 UNIQUE 约束：
            col → RefTable.ref_col
            UNIQUE(col) / UNIQUE(col1, col2, ...)
    """
    dot = Digraph(name=graph_name, format="svg")

    # 全局布局与节点/边样式（减小字号）
    dot.attr(rankdir="BT")   # Top → Bottom，从上到下
    dot.attr("node", shape="record", fontsize="16")
    dot.attr("edge", fontsize="16")

    # 1) 表节点
    for table_name, info in tables.items():
        pk_cols = set(info["pk"])
        fk_cols = {col for (col, _rt, _rc) in info["fks"]}
        all_cols = set(info["columns"])

        # 极端情况：没有 columns，但有 pk（兜底）
        if not all_cols and pk_cols:
            all_cols = set(pk_cols)

        other_cols = all_cols - pk_cols - fk_cols

        pk_lines = [f"{col} (PK)" for col in sorted(pk_cols)]
        fk_lines = [f"{col} (FK)" for col in sorted(fk_cols)]
        other_lines = [col for col in sorted(other_cols)]

        cols_lines = pk_lines + fk_lines + other_lines

        label = "{%s|%s}" % (
            table_name,
            "\\l".join(cols_lines) + "\\l" if cols_lines else ""
        )
        dot.node(table_name, label=label)

    # 2) 外键边
    for table_name, info in tables.items():
        uniques = info.get("uniques", [])

        for (col, ref_table, ref_col) in info["fks"]:
            # 被引用表可能不在当前 schema，也给一个简节点
            if ref_table not in tables:
                dot.node(ref_table, label="{%s}" % ref_table)

            base_label = f"{col} → {ref_table}.{ref_col}"

            # 找出所有包含该列的 UNIQUE 约束
            related_uqs = [uq for uq in uniques if col in uq]
            if related_uqs:
                # 为了可读性，只展示“最小集合”的 UNIQUE（避免重复）
                # 这里只取第一个即可，复杂情况你暂时用不到
                uq_set = sorted(related_uqs[0])
                uq_text = ", ".join(uq_set)
                edge_label = base_label + f"\\lUNIQUE({uq_text})"
            else:
                edge_label = base_label

            dot.edge(table_name, ref_table, label=edge_label)

    return dot


# ==========================
# main
# ==========================
def main():
    try:
        with open(INPUT_SQL, "r", encoding="utf-8") as f:
            sql_text = f.read()
    except FileNotFoundError:
        print(f"错误：找不到 SQL 文件：{INPUT_SQL}")
        sys.exit(1)

    tables = parse_sql_schema(sql_text)
    if not tables:
        print("没有在 SQL 中解析到任何 CREATE TABLE 语句，请检查 INPUT_SQL。")
        sys.exit(1)

    dot = build_er_graph(tables)
    dot.render(filename=OUTPUT_BASENAME, format="svg", cleanup=True)
    print(f"生成成功：{OUTPUT_BASENAME}.svg")


if __name__ == "__main__":
    main()
