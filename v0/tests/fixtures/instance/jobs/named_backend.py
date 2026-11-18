async def main(job):
    result = await job.run_node("refresh", {"sources": "polars"}, backend="scripted")
    return f"refresh {result['outcome']}"
