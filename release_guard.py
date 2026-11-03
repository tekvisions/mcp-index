"""Temporary publication hold for the legacy MCP pipeline.

The current collector truncates at 60 pages and the generator removes routes.
No environment variable, record-count threshold or date can release this hold.
Replace this guard only with the reviewed cursor-complete, route-preserving,
bounded package pipeline after its data, package and provider checks pass.
"""
import sys

class PublicationHeld(RuntimeError):
    pass

def require_reviewed_pipeline():
    raise PublicationHeld(
        'MCP legacy refresh is held: the 60-page collector has no bound '
        'cursor-completeness receipt and its generator deletes prior routes. '
        'Current data, published routes and deployment are preserved. '
        'The reviewed full-collection, route-preserving package pipeline must '
        'pass its release gates before this hold is replaced. '
        'No collection, commit, upload or IndexNow submission is authorized '
        'through this legacy pipeline while held.'
    )

def main():
    try:
        require_reviewed_pipeline()
    except PublicationHeld as error:
        print(str(error),file=sys.stderr)
        return 2

if __name__=='__main__':
    sys.exit(main())
