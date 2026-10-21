import {defineConfig} from 'vite';
export default defineConfig({base:'./',cacheDir:'cache/vite',server:{host:'127.0.0.1',port:5180,strictPort:true},build:{emptyOutDir:false}});
