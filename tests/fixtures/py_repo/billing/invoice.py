from shop import prices


def make_invoice(items):
    return {"total": prices.sum_prices(items)}
