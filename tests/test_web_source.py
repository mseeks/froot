"""The web-source loader: read changed templates, skip non-templates."""

from __future__ import annotations

from pathlib import Path

from froot.adapters.web_source import load_web_sources


def test_loads_templates_skips_others_and_missing(tmp_path: Path):
    (tmp_path / "components").mkdir()
    (tmp_path / "components" / "A.vue").write_text(
        "<template><img /></template>\n", encoding="utf-8"
    )
    (tmp_path / "B.jsx").write_text("<img />\n", encoding="utf-8")
    (tmp_path / "store.ts").write_text("export const x = 1\n", encoding="utf-8")

    sources = load_web_sources(
        tmp_path,
        ("components/A.vue", "B.jsx", "store.ts", "gone/Missing.vue"),
    )

    by_path = {s.path: s for s in sources}
    assert set(by_path) == {"components/A.vue", "B.jsx"}  # .ts + missing skip
    assert by_path["components/A.vue"].dialect == "vue"
    assert by_path["B.jsx"].dialect == "jsx"
    assert by_path["components/A.vue"].lines[0].startswith("<template>")
