async def main(job):
    result = await job.run_node("refresh", {"sources": "polars"})
    return {"returned": [result]}
