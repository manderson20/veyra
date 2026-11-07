# Prompt: add a firmware release to a capability pack

Give this to Claude Code in the Veyra repository, together with the vendor's
release notes and, if you have it, the admin guide for that release (a PDF or
a link). Fill in the three lines at the top.

---

Vendor and family: `<for example yealink/t4x>`
Firmware release: `<for example 86.80>`
Documents attached: `<titles and versions>`

Add this firmware release to Veyra's capability pack for the family above,
following `docs/CAPABILITY_CATALOG.md`. Work on a new branch.

1. **Read first:** `docs/CAPABILITY_CATALOG.md`, the family's
   `family.toml`, and every existing release file of the family, so you know
   what the newest release already says.
2. **Write the release file** `provisioning/capabilities/<pack>/<family>/<version>.toml`:
   - `extends` the newest earlier release of the family. Under
     `firmware_packaging = "model"`, list the models the release is for.
   - List only what this release changes: `[added.…]`, `[changed.…]`,
     `[deprecated.…]`, `[removed.…]`. Put nothing in it that the documents
     don't say.
   - Give every entry a `source` with the document, the section and the page.
     Add each document under `[release.sources]` with its title and version.
     Never paste long passages; cite them.
   - Use `provenance = "vendor-doc"` for what the documents state.
3. **Never guess a rule.** When the documents don't give a setting's values,
   range, type or the models it applies to plainly, leave that rule out and
   add an item to the open questions (step 6). A rule that is too strict
   stops administrators' saves for no reason.
4. **Supported models:** if the release notes list supported models that
   differ from `pack.toml`'s `[[supports]]`, update that entry with the
   citation and say so in the pull request.
5. **Check:**
   - `cd backend && .venv/bin/veyra packs validate ../provisioning/capabilities/<pack>`
   - `.venv/bin/veyra packs check ../provisioning/capabilities/<pack> --templates ../provisioning/templates`
   - `.venv/bin/pytest -q tests/test_capabilities.py tests/test_config_precheck.py`

   Report every setting an official template writes that the new release
   would refuse or warn about, with the model and the rule. Do not change a
   template or weaken an entry to make a check pass; report it.
6. **Open a pull request** with:
   - the release and documents used,
   - a table of the changes (added, changed, deprecated, removed) with their
     citations,
   - what `packs check` reports for the official templates on the new
     release,
   - **Open questions:** every setting the documents left unclear, what was
     unclear, and the page,
   - a CHANGELOG line under Unreleased (`### Changed`: "Vendor data:
     <family> firmware <version>").
