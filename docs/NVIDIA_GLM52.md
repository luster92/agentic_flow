# NVIDIA GLM-5.2 elevation

Clawflow can use NVIDIA Build's hosted GLM-5.2 endpoint as a provider-independent elevation target.

## Endpoint

- LiteLLM alias: `nvidia-glm52`
- Upstream model: `z-ai/glm-5.2`
- API base: `https://integrate.api.nvidia.com/v1`
- Secret: `NVIDIA_API_KEY`

## Intended use

This deployment is not a general first-choice route. It is selected when a non-local-only request starts on `local-quality` and the local Worker explicitly requests escalation because validation, critic review, or execution quality failed.

Direct cloud requests continue to use the task-specific aliases selected by `ModelPolicy` (`cloud-coding`, `cloud-reasoning`, and similar aliases).

## Privacy boundary

Requests with `local_only=true` must never elevate to this endpoint.

## Configuration

Set the API key before starting the LiteLLM proxy:

```bash
export NVIDIA_API_KEY="..."
litellm --config config.yaml --port 4000
```

The NVIDIA endpoint is OpenAI-compatible. Concrete provider details remain in `config.yaml`; agents and orchestration code consume only the `nvidia-glm52` alias.
