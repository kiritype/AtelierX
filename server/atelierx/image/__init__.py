"""Image module (decision 0018): image generation server connection, generation, review, tools and LoRA training.

Ported from the author's earlier image tool and fitted to AtelierX data (character items, design.json, image library).
The runtime is thread based; API handlers call it through Starlette's thread pool.
"""
