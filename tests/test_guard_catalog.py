"""The guard's refusal list against the engine's whole function catalog.

The static layer refuses functions by name, which is only as good as the list. This test asks the installed Relate
for every function it has (`SHOW FUNCTIONS`) and requires each one to sit in exactly one reviewed class below. A Relate
release that adds or renames a function fails here until someone classifies it, so on the pinned engine no function
reaches a query unreviewed. (Writes do not depend on this list: Relate's own `query_type` must be "r".)
"""

import pytest
import relate

from witness.guard import Refused, static_checks

# refused in every call form: random, clock, store ids, a tied path choice, server namespaces
ALWAYS_REFUSED = {
    "db.nameFromElementId", "elementId", "graph.byElementId", "graph.byName", "graph.names", "graph.propertiesByName",
    "id", "rand", "randomUUID", "shortestPath", "timestamp", "uuid",
}  # fmt: skip
# temporal constructors and their namespaced forms: refused when they read the clock (no argument, a non-literal
# argument, .realtime/.statement/.transaction, a .truncate without an input), allowed with literal values
TEMPORAL_FORMS = {
    "date", "date.realtime", "date.statement", "date.transaction", "date.truncate", "datetime", "datetime.fromepoch",
    "datetime.fromepochmillis", "datetime.realtime", "datetime.statement", "datetime.transaction", "datetime.truncate",
    "local_datetime", "local_time", "localdatetime", "localdatetime.realtime", "localdatetime.statement",
    "localdatetime.transaction", "localdatetime.truncate", "localtime", "localtime.realtime", "localtime.statement",
    "localtime.transaction", "localtime.truncate", "time", "time.realtime", "time.statement", "time.transaction",
    "time.truncate", "zoned_datetime", "zoned_time",
}  # fmt: skip
# reviewed as a function of its arguments and the graph alone (`file` and `linenumber` exist only inside LOAD CSV,
# which is refused; order-dependent uses such as head(collect(x)) are the reverse-order check's job, not this list's)
DETERMINISTIC = {
    "abs", "acos", "all", "allReduce", "allShortestPaths", "any", "asin", "atan", "atan2", "avg", "btrim",
    "cardinality", "ceil", "ceiling", "char_length", "character_length", "coalesce", "coll.distinct", "coll.flatten",
    "coll.indexOf", "coll.insert", "coll.max", "coll.min", "coll.remove", "coll.sort", "collect", "collect_list", "cos",
    "cosh", "cot", "coth", "count", "degrees", "duration", "duration.between", "duration.inDays", "duration.inMonths",
    "duration.inSeconds", "duration_between", "e", "endNode", "exists", "exp", "file", "floor", "format", "haversin",
    "head", "isEmpty", "isNaN", "keys", "labels", "last", "left", "length", "linenumber", "ln", "log", "log10", "lower",
    "ltrim", "max", "min", "nodes", "none", "normalize", "nullIf", "path_length", "percentileCont", "percentileDisc",
    "percentile_cont", "percentile_disc", "pi", "point", "point.distance", "point.withinBBox", "properties",
    "property_exists", "radians", "range", "reduce", "relationships", "replace", "reverse", "right", "round", "rtrim",
    "sign", "sin", "single", "sinh", "size", "split", "sqrt", "stDev", "stDevP", "startNode", "stdev_pop",
    "stdev_samp", "string.indexOf", "string.join", "string.regexReplace", "substring", "sum", "tail", "tan", "tanh",
    "toBoolean", "toBooleanList", "toBooleanOrNull", "toFloat", "toFloatList", "toFloatOrNull", "toInteger",
    "toIntegerList", "toIntegerOrNull", "toLower", "toString", "toStringList", "toStringOrNull", "toUpper", "trim",
    "type", "upper", "uuid.leastSignificantBits", "uuid.mostSignificantBits", "valueType", "vector",
    "vector.similarity.cosine", "vector.similarity.euclidean", "vector_dimension_count", "vector_distance",
    "vector_norm",
}  # fmt: skip


def test_every_function_of_the_installed_relate_is_classified():
    db = relate.Database(":memory:")
    try:
        catalog = {r["name"] for r in db.execute("SHOW FUNCTIONS").data}
    finally:
        db.close()
    classes = (ALWAYS_REFUSED, TEMPORAL_FORMS, DETERMINISTIC)
    assert sum(len(c) for c in classes) == len(set().union(*classes)), "a function sits in two classes"
    unclassified = sorted(catalog - set().union(*classes))
    assert not unclassified, f"Relate {relate.__version__} has functions the guard has not reviewed: {unclassified}"
    assert not sorted(set().union(*classes) - catalog), "a classified function is gone from the catalog"
    for name in sorted(ALWAYS_REFUSED):
        with pytest.raises(Refused):
            static_checks(f"RETURN {name}($x) AS v", {"x": 1})
    for name in sorted(TEMPORAL_FORMS - {"datetime.fromepoch", "datetime.fromepochmillis"}):
        with pytest.raises(Refused):  # no literal date/time value: it would read the clock, or the form is unknown
            static_checks(f"RETURN {name}() AS v")
    for name in sorted(DETERMINISTIC | {"datetime.fromepoch", "datetime.fromepochmillis"}):
        static_checks(f"RETURN {name}($x) AS v", {"x": 1})  # the static layer lets it through
