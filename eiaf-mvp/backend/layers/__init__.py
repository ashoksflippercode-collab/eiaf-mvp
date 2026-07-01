"""EIAF pipeline layers (PRD §3).

Each layer is an independently testable module exposing a single class entry
point that consumes and returns the shared envelope. The canonical Tier-1 order
is: Intent -> Orchestration -> Semantic -> Service -> Data -> Response.
"""
