# Icons placeholder

For M1 we ship without a custom icon. Tauri uses a default placeholder.

For M5 (polish), generate the icon set with:

```
pnpm tauri icon path/to/source.png
```

This produces `icon.ico`, multiple `.png` sizes, and platform-specific bundles under this directory.
