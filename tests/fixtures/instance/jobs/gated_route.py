async def main(job):
    result = await job.run_node("gated_route", {})
    return {"returned": [result]}
