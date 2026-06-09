from __future__ import annotations

import pytest
from pydantic import ValidationError

from froot.domain.dead_source import DeadExport, DeadFile
from froot.domain.ecosystem import Ecosystem
from froot.policy.dead_source import unexport_line


def test_dead_file_subject_and_str():
    item = DeadFile(path="src/old/util.ts", ecosystem=Ecosystem.NPM)
    assert item.kind == "dead_file"
    assert item.subject == "src/old/util.ts"  # the path is its identifier
    assert str(item) == "delete src/old/util.ts (unused)"


def test_dead_export_subject_and_str():
    item = DeadExport(
        file="src/util.ts", symbol="helper", line=12, ecosystem=Ecosystem.NPM
    )
    assert item.kind == "dead_export"
    assert item.subject == "helper"  # the symbol is its identifier
    assert str(item) == "un-export helper in src/util.ts (unused)"


def test_dead_export_line_must_be_positive():
    # The analyzer's position is 1-based; a non-positive line can't exist.
    with pytest.raises(ValidationError):
        DeadExport(
            file="src/util.ts", symbol="x", line=0, ecosystem=Ecosystem.NPM
        )


def test_dead_file_path_must_be_nonempty():
    with pytest.raises(ValidationError):
        DeadFile(path="", ecosystem=Ecosystem.NPM)


# (line, symbol, expected) — the inline declaration forms the action handles,
# plus the forms it must refuse (returns None so the signal drops them).
_UNEXPORT_CASES = [
    ("export function foo() {", "foo", "function foo() {"),
    ("export const foo = 1", "foo", "const foo = 1"),
    ("export let foo = 1", "foo", "let foo = 1"),
    ("export class Foo {", "Foo", "class Foo {"),
    ("export interface I {", "I", "interface I {"),
    ("export type Foo = number", "Foo", "type Foo = number"),
    ("export enum E {", "E", "enum E {"),
    ("export async function foo() {", "foo", "async function foo() {"),
    ("export abstract class Base {", "Base", "abstract class Base {"),
    ("  export const inner = 1", "inner", "  const inner = 1"),
    # Refused: the named symbol is not the one this line declares.
    ("export const foo = 1", "bar", None),
    # Refused: a default export has no plain un-exported form.
    ("export default function foo() {", "foo", None),
    # Refused: clause re-exports / star re-exports need an AST, not a line edit.
    ("export { foo, bar }", "foo", None),
    ("export * from './x'", "foo", None),
    # Refused: a destructuring export declares no single identifier here.
    ("export const { a } = obj", "a", None),
    # Refused: the line is not an export at all.
    ("const foo = 1", "foo", None),
]


@pytest.mark.parametrize(("line", "symbol", "expected"), _UNEXPORT_CASES)
def test_unexport_line(line: str, symbol: str, expected: str | None):
    assert unexport_line(line, symbol) == expected
