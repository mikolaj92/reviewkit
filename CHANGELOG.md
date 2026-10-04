# Changelog

## Unreleased

ReviewKit reviews one DOCX by walking that same file: zdanie, then akapit,
then rozdział, then całość. On a unit, stay or go. Stay may add, update, or
delete a Word comment, or change text as tracked insert / delete / replace,
through one open Docxtor handle (0.17.0, `4abb4800`). Go moves to the next
unit.

A stay that deletes or inserts a sentence rebuilds positional ids such as
`p1.s2`. The walk now refreshes the current unit after that change and
continues after it, so a middle delete no longer drops later sentences or
higher levels, a stay after delete does not attach to the next sentence,
and a sentence created during the zdanie phase is visited.
