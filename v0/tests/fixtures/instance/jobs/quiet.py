async def main(job):
    result = await job.run_node("locate_quiet", {"source": "polars"})
    return {"returned": [result]}
