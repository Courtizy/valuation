"""L2 Models: valuation plug-ins plus cross-model reconciliation.

Isolation rules (enforced by tests/test_L2_isolation.py):
  - a model may import L2_models.base and core utilities, never another model
  - reconcile reads model_results/*.json files and imports no model
"""
