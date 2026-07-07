export function linearSearch(items, target) {
    for (let index = 0; index < items.length; index += 1) {
        if (items[index] === target) {
            return index;
        }
    }
    return -1;
}
export function binarySearch(sortedItems, target) {
    let left = 0;
    let right = sortedItems.length - 1;
    while (left <= right) {
        const middle = Math.floor((left + right) / 2);
        if (sortedItems[middle] === target) {
            return middle;
        }
        if (sortedItems[middle] < target) {
            left = middle + 1;
        }
        else {
            right = middle - 1;
        }
    }
    return -1;
}
