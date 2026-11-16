void *memset(void *p, char c, unsigned n)
{
    for(unsigned i = 0; i < n; ++i) {
        ((char *)p)[i] = c;
    }

    return p;
}
