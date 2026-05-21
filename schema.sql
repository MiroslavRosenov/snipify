CREATE TABLE IF NOT EXISTS public.urls (
	id SERIAL NOT NULL,
    origin TEXT NOT NULL,
    alias TEXT NOT NULL,

    PRIMARY KEY (id)
);
