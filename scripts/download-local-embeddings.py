"""Download the pinned Apache-2.0 model files during online setup only."""

from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="sentence-transformers/all-MiniLM-L6-v2",
    revision="1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
    local_dir="data/local/models/all-MiniLM-L6-v2",
    allow_patterns=[
        "model.safetensors", "*.json", "vocab.txt", "1_Pooling/config.json", "README.md",
    ],
)
