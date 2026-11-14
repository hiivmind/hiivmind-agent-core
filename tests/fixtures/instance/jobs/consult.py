async def main(job):
    try:
        await job.call("tools__lookup", {"key": "missing"})
        raised = "nothing was raised"
    except Exception as e:
        raised = f"{type(e).__name__}: {e}"
    where = await job.call("locate", {"source": "ibis"})
    await job.call("locate", {"source": "narwhals"})
    await job.run_node("consult", {})
    await job.run_node("locate", {"source": "polars"})
    return {"raised": raised, "where": where}
