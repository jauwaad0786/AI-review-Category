USE easemydeal_tbl_seller_review;

-- tbl_seller_review table

CREATE INDEX idx_tbl_seller_review_status
    ON tbl_seller_review (status);

CREATE INDEX idx_tbl_seller_review_status_processed
    ON tbl_seller_review (status, is_processed);

CREATE INDEX idx_tbl_seller_review_seller_status
    ON tbl_seller_review (seller_profile_id, status);

CREATE INDEX idx_tbl_seller_review_created
    ON tbl_seller_review (created_at);


-- tbl_seller_review_analysis table

CREATE INDEX idx_ra_review_id
    ON tbl_seller_review_analysis (review_id);

CREATE INDEX idx_ra_seller_profile_id
    ON tbl_seller_review_analysis (seller_profile_id);







-- tbl_seller_category_rating

CREATE UNIQUE INDEX idx_scr_seller_category
    ON tbl_seller_category_rating (seller_profile_id, category);