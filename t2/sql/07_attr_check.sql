WITH components AS (
    SELECT node, component
    FROM pgr_connectedComponents(%(edges_sql)s)
),
key_labels AS (
    SELECT k.node_id,
           CASE WHEN a.is_anchored THEN COALESCE(c.component, -k.node_id) ELSE -k.node_id END AS label
    FROM key_nodes k
    JOIN key_node_anchors a ON a.node_id = k.node_id AND a.scenario = %(scenario)s
    LEFT JOIN components c ON c.node = a.vertex_id
    WHERE %(include_rapa_nui)s OR NOT k.is_rapa_nui
),
groups AS (
    SELECT label, count(*) AS members
    FROM key_labels
    GROUP BY label
),
totals AS (
    SELECT sum(members) AS n, sum(members * (members - 1) / 2) AS connected_pairs
    FROM groups
)
SELECT n,
       n * (n - 1) / 2 AS total_pairs,
       connected_pairs,
       connected_pairs::double precision / (n * (n - 1) / 2) AS attr
FROM totals;
