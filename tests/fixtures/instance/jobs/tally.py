async def main(job):
    direct = await job.call("count_words", {"text": "alpha beta gamma"})
    await job.run_node("tally", {})
    try:
        await job.call("read_ledger", {"name": "main"})
        raised = "nothing was raised"
    except Exception as e:
        raised = f"{type(e).__name__}: {e}"
    await job.run_node("ledger", {})
    return {"direct": direct, "raised": raised}
