# CP25 shadow sweep speedup

The sweep currently asks inspect for callback source locations for every
matched (state,probe,handler), repeatedly reading/scanning the same source.
This metadata has no influence on whether a filter matches. Cache only the
source location per callback identity inside one sweep invocation.

`matching_handlers` will accept an optional local location dictionary. A
standalone call gets fresh metadata as before. `sweep` creates one dictionary
and passes it to every matching call, then discards it on return. Callback
objects remain held by the live dispatcher throughout the sweep, so their
identity cannot be reused during that invocation.

Keep every declared state, generated probe, router traversal, router filter,
handler filter, ordering and diagnostic tuple unchanged. Never cache filter
results: they may depend on raw state, event, kwargs or side effects. Never
use a module/global metadata cache: a subsequent sweep must see edited source.

Tiny focused regression uses two synthetic states and two messages. It checks
all filter calls (four per handler per sweep), the exact duplicate diagnostic,
two metadata lookups, and fresh lookups in a second invocation. This does not
run either production matrix. Mutation proof must catch bypassing the metadata
cache, bypassing the filter call, and reuse across invocations.

Both full production shop/platform sweeps and elapsed-time comparison are
queued until actual free RAM >=3072MiB. Do not describe the speedup as measured
until those run. Source-location caching is now implemented; tiny RED then
GREEN proved unchanged exact duplicate/filter counts and fresh metadata across
two invocations. Full sweeps have NOT run. New assertion mutation proof follows
in the daytime pass. The deprecated tonight queue must not be used to bypass
the25-shop attribution review before AFTER; see current CP25_STATUS command.
