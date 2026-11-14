async def main(job):
    result = await job.run_node("shape", {})
    return {"returned": [result]}
