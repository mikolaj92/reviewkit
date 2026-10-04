# Changelog

## Unreleased

ReviewKit reviews one DOCX by walking that same file: zdanie, then akapit,
then rozdział, then całość. On a unit, stay or go. Stay may add, update, or
delete a Word comment, or change text as tracked insert / delete / replace,
through one open Docxtor handle (0.15.0, `608336b0`). Go moves to the next
unit.
