USE easemydeal_reviews;

-- reviews table

CREATE INDEX idx_reviews_status
    ON reviews (status);

CREATE INDEX idx_reviews_status_processed
    ON reviews (status, is_processed);

CREATE INDEX idx_reviews_seller_status
    ON reviews (seller_id, status);

CREATE INDEX idx_reviews_created
    ON reviews (created_at);


-- review_analysis table

CREATE INDEX idx_ra_review_id
    ON review_analysis (review_id);

CREATE INDEX idx_ra_seller_id
    ON review_analysis (seller_id);


-- tbl_seller_rating

CREATE UNIQUE INDEX idx_sr_seller_id
    ON tbl_seller_rating (seller_id);


-- tbl_seller_category_rating

CREATE UNIQUE INDEX idx_scr_seller_category
    ON tbl_seller_category_rating (seller_id, category);