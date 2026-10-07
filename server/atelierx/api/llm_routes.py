"""LLM connections, their models and the usage log."""

import csv
import io
from datetime import datetime

from starlette.responses import Response
from starlette.routing import Route

from .common import body, ok, st


async def providers_get(request):
    return ok(st(request).llm.doc())


async def providers_put(request):
    return ok(st(request).llm.save(await body(request)))


def _usage_month(request):
    return request.query_params.get('month') or datetime.now().astimezone().strftime('%Y-%m')


async def usage(request):
    month = _usage_month(request)
    llm = st(request).llm
    return ok(
        {
            'month': month,
            'months': llm.usage_months(),
            'tasks': llm.usage_tasks(month),
            'rows': llm.usage(month, request.query_params.get('by', 'model')),
        }
    )


async def usage_log(request):
    q = request.query_params
    return ok(
        st(request).llm.usage_log(
            _usage_month(request),
            q.get('offset', 0),
            q.get('limit', 50),
            q.get('work') or None,
            q.get('task') or None,
        )
    )


async def usage_csv(request):
    """The month's requests as CSV (UTF-8 with BOM so spreadsheet programs read Korean names)."""
    month = _usage_month(request)
    out = io.StringIO()
    fields = ['at', 'provider', 'model', 'task', 'work', 'input_tokens', 'output_tokens']
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    for entry in st(request).llm.usage_entries(month):
        writer.writerow(entry)
    return Response(
        '\ufeff' + out.getvalue(),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="atelierx-usage-{month}.csv"'},
    )


async def providers_models(request):
    return ok({'models': await st(request).llm.models(request.path_params['pid'])})


async def providers_model_info(request):
    llm = st(request).llm
    return ok(await llm.model_info(request.path_params['pid'], request.query_params.get('model')))


async def providers_probe(request):
    return ok(await st(request).llm.probe(request.path_params['pid']))


def routes():
    return [
        Route('/api/providers', providers_get),
        Route('/api/providers', providers_put, methods=['PUT']),
        Route('/api/providers/{pid}/models', providers_models),
        Route('/api/providers/{pid}/probe', providers_probe, methods=['POST']),
        Route('/api/providers/{pid}/model-info', providers_model_info),
        Route('/api/usage', usage),
        Route('/api/usage/log', usage_log),
        Route('/api/usage.csv', usage_csv),
    ]
