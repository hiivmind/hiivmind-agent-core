async def main(job):
    # `refresh` declares `sources`; `source` is a mistake the harness should not swallow.
    result = await job.run_node("refresh", {"source": "polars"})
    return f"refresh {result['outcome']}"
