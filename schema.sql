CREATE TABLE IF NOT EXISTS public.urls (
	id SERIAL NOT NULL,
    origin TEXT NOT NULL,
    alias TEXT NOT NULL,
    created_by BIGINT NOT NULL,

    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS public.users (
	id SERIAL NOT NULL,
    email TEXT NOT NULL,
    hashed_password TEXT NOT NULL,
    verified BOOLEAN NOT NULL DEFAULT False,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),    -- UTC native table

    PRIMARY KEY (email)
);
