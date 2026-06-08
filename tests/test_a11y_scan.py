"""Pure tests for the dialect-aware source-level a11y sweep."""

from __future__ import annotations

from froot.policy.a11y_scan import WebSource, dialect_for, scan_sources

_VUE = WebSource(
    path="components/Widget.vue",
    dialect="vue",
    lines=tuple(
        """\
<template>
  <div>
    <svg viewBox="0 0 1 1"><path d="" /></svg>
    <span role="img">📷</span>
    <img :src="u" />
    <label for="name">Name</label>
    <input id="name" type="text" />
    <input type="range" data-testid="when" />
    <li role="button" tabindex="0" @click="go" @keydown.enter="go">x</li>
    <div
      class="card"
      @click.stop="open"
    >menu</div>
  </div>
</template>
""".splitlines()
    ),
)

_JSX = WebSource(
    path="src/Widget.jsx",
    dialect="jsx",
    lines=tuple(
        """\
export function Widget() {
  return (
    <div>
      <svg><path /></svg>
      <img src={u} />
      <input id="email" type="text" />
      <label htmlFor="email">Email</label>
      <div onClick={open}>menu</div>
      <button onClick={close} aria-label="Close" />
      <MyThing onClick={noop} />
      <span role="img">x</span>
    </div>
  );
}
""".splitlines()
    ),
)


def _kinds(path: str) -> list[str]:
    src = _VUE if path == _VUE.path else _JSX
    return [c.kind for c in scan_sources((src,)) if c.file == path]


def test_dialect_for():
    assert dialect_for("a/b.vue") == "vue"
    assert dialect_for("a/b.jsx") == "jsx"
    assert dialect_for("a/b.tsx") == "jsx"
    assert dialect_for("a/b.ts") is None
    assert dialect_for("a/b.css") is None


def test_vue_flags_every_kind():
    kinds = _kinds(_VUE.path)
    assert kinds.count("svg") == 1
    assert kinds.count("image") == 1
    assert kinds.count("role-img") == 1
    assert kinds.count("labelable") == 2
    # The <li> and the multi-line <div> both carry a click handler.
    assert kinds.count("clickable-nonbutton") == 2


def test_clickable_detail_and_multiline_tag():
    cands = scan_sources((_VUE,))
    clicks = {c.detail for c in cands if c.kind == "clickable-nonbutton"}
    # The handler sits three lines below its <div, found by the backward walk.
    assert clicks == {"<li>", "<div>"}


def test_label_wiring_resolved_for_id_but_not_for_range():
    cands = scan_sources((_VUE,))
    labelable = [c for c in cands if c.kind == "labelable"]
    wired = {c.label_wired for c in labelable}
    # The id-wired <input id="name"> is resolved; the range slider is not.
    assert wired == {True, False}


def test_jsx_dialect_and_interactive_skip():
    kinds = _kinds(_JSX.path)
    assert "svg" in kinds
    assert "image" in kinds
    assert "role-img" in kinds
    assert kinds.count("labelable") == 1
    # onClick on <div> is flagged; on <button> (native) and <MyThing>
    # (a component) it is not.
    assert kinds.count("clickable-nonbutton") == 1


def test_jsx_label_wired_via_htmlfor():
    cands = scan_sources((_JSX,))
    [control] = [c for c in cands if c.kind == "labelable"]
    assert control.label_wired is True


def test_vue_click_regex_does_not_match_jsx_onclick():
    # A Vue file using onClick (not a Vue handler) yields no clickable finding.
    src = WebSource(
        path="x.vue",
        dialect="vue",
        lines=("<div onClick='x'>y</div>",),
    )
    assert not [
        c for c in scan_sources((src,)) if c.kind == "clickable-nonbutton"
    ]


def test_candidate_carries_context_window():
    [first, *_] = scan_sources((_VUE,))
    assert first.context  # the model gets surrounding lines, not just the hit
    assert first.dialect == "vue"


def test_clickable_attributed_to_wrapper_not_a_child_anchor():
    # The handler belongs to the <div> it is inside, not the <a> that closes
    # after it — a naive "last tag on the line" walk would drop this gap.
    src = WebSource(
        path="x.vue",
        dialect="vue",
        lines=('<div @click="open"><a href="/x">link</a></div>',),
    )
    clicks = [
        c for c in scan_sources((src,)) if c.kind == "clickable-nonbutton"
    ]
    assert len(clicks) == 1
    assert clicks[0].detail == "<div>"


def test_vue_v_on_click_long_form_is_flagged():
    src = WebSource(
        path="x.vue",
        dialect="vue",
        lines=('<div v-on:click.stop="go">menu</div>',),
    )
    assert [c for c in scan_sources((src,)) if c.kind == "clickable-nonbutton"]


def test_label_wiring_requires_a_real_live_label():
    # An <output for> and a commented-out <label> do NOT name the control.
    src = WebSource(
        path="x.vue",
        dialect="vue",
        lines=(
            '  <output for="qty">0</output>',
            '  <!-- <label for="qty">old</label> -->',
            '  <input id="qty" type="number" />',
        ),
    )
    [ctrl] = [c for c in scan_sources((src,)) if c.kind == "labelable"]
    assert ctrl.label_wired is False
    # A real, live <label for> flips it true.
    src2 = WebSource(
        path="x.vue",
        dialect="vue",
        lines=('  <label for="qty">Qty</label>', '  <input id="qty" />'),
    )
    [ctrl2] = [c for c in scan_sources((src2,)) if c.kind == "labelable"]
    assert ctrl2.label_wired is True


def test_custom_element_not_matched_as_a_native_control():
    src = WebSource(
        path="x.vue", dialect="vue", lines=("<input-mask v-model='x' />",)
    )
    assert not [c for c in scan_sources((src,)) if c.kind == "labelable"]
