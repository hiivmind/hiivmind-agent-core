async def main(job):
    result = await job.run_node("stuck", {})
    if result["outcome"] == "failed":
        # A node's own `failed` exit carries no reason; only the harness's failures do.
        raise RuntimeError(f"stuck failed: {result.get('reason', 'the node exited failed')}")
    return "stuck done"
