-- ==============================================================================
-- BOMwala: Clean Overload & Apply Weighted Smart Discovery RPC
-- ==============================================================================

-- 1. Drop all previous overloaded variants so PostgREST has no ambiguity (PGRST203 fix)
DROP FUNCTION IF EXISTS public.search_bomwala_components(text, text[], text, text, boolean, numeric, numeric, text, integer, integer, integer);
DROP FUNCTION IF EXISTS public.search_bomwala_components(text, text[], text, text, boolean, numeric, numeric, text, integer, integer, bigint);

-- 2. Create the unified single signature function with seed_val bigint
CREATE OR REPLACE FUNCTION public.search_bomwala_components(
    q text DEFAULT '',
    store_filter text[] DEFAULT NULL,
    cat_filter text DEFAULT NULL,
    subcat_filter text DEFAULT NULL,
    in_stock_only boolean DEFAULT true,
    min_price numeric DEFAULT NULL,
    max_price numeric DEFAULT NULL,
    sort_by text DEFAULT 'relevance',
    page_num int DEFAULT 1,
    page_limit int DEFAULT 35,
    seed_val bigint DEFAULT 1
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_start_time timestamp := clock_timestamp();
    v_offset int;
    v_total bigint;
    v_total_pages int;
    v_results jsonb;
    v_took_ms numeric;
    v_q text := trim(COALESCE(q, ''));
BEGIN
    v_offset := (GREATEST(page_num, 1) - 1) * GREATEST(page_limit, 1);

    -- 1. Count matching rows
    SELECT COUNT(*) INTO v_total
    FROM public.components c
    WHERE
        (store_filter IS NULL OR c.store = ANY(store_filter))
        AND (cat_filter IS NULL OR c.category = cat_filter)
        AND (subcat_filter IS NULL OR c.subcategory = subcat_filter)
        AND (NOT in_stock_only OR c.is_in_stock = 1)
        AND (min_price IS NULL OR c.price_bdt >= min_price)
        AND (max_price IS NULL OR c.price_bdt <= max_price)
        AND (
            v_q = ''
            OR c.name ILIKE ('%' || v_q || '%')
            OR c.search_tokens ILIKE ('%' || v_q || '%')
            OR c.category ILIKE ('%' || v_q || '%')
        );

    v_total_pages := CEIL(v_total::numeric / GREATEST(page_limit, 1));

    -- 2. Fetch paginated results with Weighted Ranking
    SELECT COALESCE(jsonb_agg(row_to_json(r)), '[]'::jsonb)
    INTO v_results
    FROM (
        SELECT
            c.id,
            c.name,
            c.store,
            c.price_bdt,
            c.stock_status,
            c.is_in_stock,
            c.stock_qty,
            c.category,
            c.subcategory,
            c.product_url,
            c.image_url,
            c.sku,
            c.package_footprint,
            c.specifications_json AS specifications,
            c.description,
            c.canonical_name,
            c.model_group_id,
            c.product_type,
            c.target_chip,
            c.is_accessory
        FROM public.components c
        WHERE
            (store_filter IS NULL OR c.store = ANY(store_filter))
            AND (cat_filter IS NULL OR c.category = cat_filter)
            AND (subcat_filter IS NULL OR c.subcategory = subcat_filter)
            AND (NOT in_stock_only OR c.is_in_stock = 1)
            AND (min_price IS NULL OR c.price_bdt >= min_price)
            AND (max_price IS NULL OR c.price_bdt <= max_price)
            AND (
                v_q = ''
                OR c.name ILIKE ('%' || v_q || '%')
                OR c.search_tokens ILIKE ('%' || v_q || '%')
                OR c.category ILIKE ('%' || v_q || '%')
            )
        ORDER BY
            -- Explicit user sort options
            CASE WHEN sort_by = 'price_asc' THEN c.price_bdt END ASC NULLS LAST,
            CASE WHEN sort_by = 'price_desc' THEN c.price_bdt END DESC NULLS LAST,
            CASE WHEN sort_by = 'name_asc' THEN c.name END ASC,

            -- Text query relevance
            CASE
                WHEN v_q <> '' AND c.name ILIKE (v_q || '%') THEN 1
                WHEN v_q <> '' AND c.name ILIKE ('%' || v_q || '%') THEN 2
                ELSE 3
            END ASC,

            -- Weighted Probabilistic Discovery for Landing / Random Explore (v_q = '')
            CASE
                WHEN (sort_by = 'relevance' OR sort_by IS NULL) AND v_q = '' THEN
                    power(
                        GREATEST(0.0001, (abs(hashtext(c.id::text || '_' || COALESCE(seed_val, 1)::text)) % 10000000)::numeric / 10000000.0),
                        1.0 / (
                            CASE
                                -- Demote generic accessories and high-cost non-component machines
                                WHEN COALESCE(c.is_accessory, 0) = 1 OR c.price_bdt > 15000 THEN 0.05

                                -- Priority 1: Iconic Maker Boards & Controllers
                                WHEN c.category = 'Microcontrollers & Dev Boards' THEN 1.00

                                -- Priority 2: Core Electronics Modules & Sensors
                                WHEN c.category = 'Sensors & Detectors' THEN 0.95
                                WHEN c.category = 'Motors, Drivers & Actuators' THEN 0.90
                                WHEN c.category = 'Wireless & Communication' THEN 0.88
                                WHEN c.category = 'Displays & Optoelectronics' THEN 0.85
                                WHEN c.category = 'Power, Batteries & Converters' THEN 0.82
                                WHEN c.category = 'Semiconductors & ICs' THEN 0.78

                                -- Priority 3: Passives & Switching
                                WHEN c.category = 'Passive Components' THEN 0.65
                                WHEN c.category = 'Switches & Relays' THEN 0.50
                                WHEN c.category = 'Connectors, Cables & Wiring' THEN 0.40

                                -- Priority 4: Tools & Fabrication
                                WHEN c.category IN ('Tools, Soldering & Testing', '3D Printing & CNC') THEN 0.25
                                WHEN c.category = 'Robotics, Chassis & Hardware' THEN 0.15
                                ELSE 0.20
                            END
                        )
                    )
            END DESC NULLS LAST,

            -- Secondary deterministic tie-breaker
            c.id ASC
        LIMIT GREATEST(page_limit, 1)
        OFFSET v_offset
    ) r;

    v_took_ms := ROUND((EXTRACT(EPOCH FROM (clock_timestamp() - v_start_time)) * 1000)::numeric, 2);

    RETURN jsonb_build_object(
        'results', v_results,
        'total', v_total,
        'page', GREATEST(page_num, 1),
        'limit', GREATEST(page_limit, 1),
        'total_pages', v_total_pages,
        'took_ms', v_took_ms
    );
END;
$$;
