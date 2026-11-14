import asyncio


async def main(job):
    a, b = await asyncio.gather(job.run_node("asker", {"who": "polars"}), job.run_node("asker", {"who": "ibis"}))
    return {"polars": a.get("outputs"), "ibis": b.get("outputs")}
