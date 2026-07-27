# ReOrch Integration Control Pack

These files are customer-onboarding templates, not production evidence.

1. Confirm `source_authority_matrix.template.json` with business and IT owners.
2. Select one incident scenario and complete `scenario_data_contract.template.json`.
3. Implement the Connector SDK and replace placeholders in `connector_manifest.template.json`.
4. Run `tools/run_connector_conformance.py` against a customer sandbox.
5. Submit schema observations before CDC payloads enter canonical storage.
6. Replay each hard constraint in at least three executed cases before activation.
7. Run the writeback certification harness only against an isolated sandbox.

Agent output may propose mappings or constraint candidates. Only named IT administrators
may activate versions, resolve quarantine, or register certification evidence.
