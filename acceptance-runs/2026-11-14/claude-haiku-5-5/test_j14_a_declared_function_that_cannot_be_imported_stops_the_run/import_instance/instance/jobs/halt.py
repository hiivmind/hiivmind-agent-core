async def main(job):
    result = await job.run_node("halt", {})
    return {"returned": [result]}
