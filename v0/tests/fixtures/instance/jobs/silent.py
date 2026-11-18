async def main(job):
    result = await job.run_node("silent", {})
    return {"returned": [result]}
