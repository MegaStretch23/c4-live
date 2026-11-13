# C4 diff: shop-demo

`HEAD~1` -> `HEAD`

## Containers
### Relations removed (2)
- `billing` -> `shop`
- `shop` -> `billing`

## Components
### Added (1)
- `shop/tax`

### Changed (1)
- `shop/cart`: dropped external imports: requests

### Relations added (2)
- `shop/cart` -> `shop/tax`
- `shop/tax` -> `shop/prices`

### Relations removed (2)
- `billing/invoice` -> `shop/prices`
- `shop/cart` -> `billing/invoice`
