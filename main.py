Filter Category Products
This route returns the products based on category and any or all size, stock, coating.
– If the filter parameter is set to size, the response will include a list of available sizes and the corresponding products.
– If a size_uuid, stock_uuid, or coating_uuid is provided, the products will be filtered accordingly based on the selected criteria.

Resource URI
1
GET /printproducts/categoryproductslist
Input Parameters
1
2
3
4
5
@param category_uuid {uuid} (Required) The UUID of Category.
@param size_uuid {uuid} (Optional) The UUID of Size.
@param stock_uuid {uuid} (Optional) The UUID of Stock.
@param coating_uuid {uuid} (Optional) The UUID of Coating.
@param filter (Optional): size/stock/coating
Sample Request
html

1
https://api.4over.com/printproducts/categoryproductslist?category_uuid=08a9625a-4152-40cf-9007-b2bbb349efec
Sample Response
JSON

1
2
3
4
5
6
7
8
9
10
11
12
13
14
15
16
17
18
19
20
21
22
23
24
25
26
27
28
29
30
31
32
33
34
35
36
37
38
39
40
41
42
43
44
45
46
47
48
49
50
51
52
53
54
55
56
57
58
59
60
61
62
63
64
65
66
67
68
69
70
71
72
73
74
75
76
77
78
79
80
81
82
83
84
85
86
87
88
89
90
91
92
93
94
95
96
97
98
99
100
101
102
103
104
105
106
107
108
109
110
111
112
113
114
115
116
117
118
119
120
121
122
123
124
{
    "size_list": [
        {
            "name": "1.5\" x 3.5\"",
            "uuid": "9ab7b563-5e4d-4bc2-a5d6-32de8b9b9e06"
        },
        {
            "name": "1.75\" x 3.5\"",
            "uuid": "1bab342a-cf16-47f9-97b6-8d880f3f096a"
        },
        {
            "name": "2\" x 2\"",
            "uuid": "977ac498-7c23-4b1f-afbd-e33d99cd44b0"
        },
        {
            "name": "2\" x 3\"",
            "uuid": "0d56dc24-f70f-46d9-b58f-b2b03e72a9a5"
        },
        {
            "name": "2\" x 3.5\"",
            "uuid": "cb23ad7e-5e87-41f9-9956-4fe91dc8820b"
        },
        {
            "name": "2\" x 7\"",
            "uuid": "fffabbf1-d425-4a65-a25d-829372471ab0"
        }
    ],
    "stock_list": [
        {
            "name": "14PT",
            "uuid": "6f4fd47a-f70f-4f3d-84f8-a78ef9a62a5a"
        },
        {
            "name": "14PTUC",
            "uuid": "c438d655-d2dd-486b-93d5-47b1f3edee19"
        },
        {
            "name": "16PT",
            "uuid": "cb84e4f5-cf63-4c25-b3c3-d22fc7dcf09d"
        },
        {
            "name": "18PTC1S",
            "uuid": "8397859c-f981-4575-b40f-daffc42e2347"
        },
        {
            "name": "100GLC",
            "uuid": "6ef3ac86-0540-4936-8f72-172257b3be60"
        }
    ],
    "coating_list": [
        {
            "name": "AQ",
            "uuid": "d41dab50-ff65-4f4f-bb17-2afe4d36ae33"
        },
        {
            "name": "MATT",
            "uuid": "121bb7b5-3b4d-429f-bd8d-bbf80e953313"
        },
        {
            "name": "SA",
            "uuid": "1753ff32-3d28-4f95-990a-6fda0dbe3d7c"
        },
        {
            "name": "SPUV",
            "uuid": "88542d07-0352-4839-9e2e-a2c8d1c343ef"
        },
        {
            "name": "UC",
            "uuid": "3e7618de-abca-4bda-9f97-8b9129e913d8"
        },
        {
            "name": "UV",
            "uuid": "ae367451-b2b8-45df-a344-0f05b6a12993"
        }
    ],
    "products": [
        {
            "product_uuid": "1a7e039c-e7ed-4410-8c64-377dbcbee322",
            "product_code": "14PT-BCUV-1.5X3.5",
            "product_description": "1.5\" X 3.5\" 14PT Business Cards UV on 4-color side(s)"
        },
        {
            "product_uuid": "62192f90-f05a-4d67-80dd-078f3f4bb7f8",
            "product_code": "14PT-BCAQ-1.5X3.5",
            "product_description": "1.5\" X 3.5\" 14PT Business Cards with AQ"
        },
        {
            "product_uuid": "aaae2989-9cc0-4057-9dec-bd66e99805b9",
            "product_code": "14PT-BCMATT-1.75X3.5",
            "product_description": "1.75\" X 3.5\" 14PT Matte/Dull Finish Business Cards"
        },
        {
            "product_uuid": "218fa68e-134a-4dfd-9c7a-1f77f507b2f1",
            "product_code": "14PT-RCBCMATT-1.75X3.5",
            "product_description": "1.75\" X 3.5\" 14PT Matte/Dull Finish Round Corner Business Card"
        },
        {
            "product_uuid": "e9629ad0-d1c2-43cf-a629-eb90646691cc",
            "product_code": "14PT-RCBCUV-1.75X3.5",
            "product_description": "1.75\" X 3.5\" 14PT Round Corner Business Cards UV on 4-color side(s)"
        },
        {
            "product_uuid": "7efe5077-7d64-44f1-8b67-5a1d0f081225",
            "product_code": "14PTUC-BCUC-1.75X3.5",
            "product_description": "1.75\" X 3.5\" 14PT Uncoated Business Cards"
        },
        {
            "product_uuid": "5fc51e71-9018-4f1e-bb3e-9bbefe96ddac",
            "product_code": "16PT-BCSPUVBK-1.75X3.5",
            "product_description": "1.75\" X 3.5\" 16PT Business Cards  with Spot UV on back only, Full UV on the front"
        },
        {
            "product_uuid": "b542104c-1475-4bc3-b280-923c416d9f7a",
            "product_code": "16PT-BCSPUV-1.75X3.5",
            "product_description": "1.75\" X 3.5\" 16PT Business Cards  with Spot UV on both sides"
        },
        {
            "product_uuid": "2ba4bb0c-9e8b-45df-9439-91cd7de3041d",
            "product_code": "16PT-BCSPUVFR-1.75X3.5",
            "product_description": "1.75\" X 3.5\" 16PT Business Cards  with Spot UV on front only, No UV Coating on the Back"
        },
        ...
    ]
}
Sample Request
html

1
https://api.4over.com/printproducts/categoryproductslist?category_uuid=08a9625a-4152-40cf-9007-b2bbb349efec&size_uuid=9ab7b563-5e4d-4bc2-a5d6-32de8b9b9e06&stock_uuid=6f4fd47a-f70f-4f3d-84f8-a78ef9a62a5a&coating_uuid=1e8116af-acfc-44b1-83dc-8181aa338834
Sample Response
JSON

1
2
3
4
5
6
7
8
9
10
11
12
13
14
15
16
17
18
19
20
21
22
23
24
25
26
27
{
    "size_list": [
        {
            "name": "1.5\" x 3.5\"",
            "uuid": "9ab7b563-5e4d-4bc2-a5d6-32de8b9b9e06"
        }
    ],
    "stock_list": [
        {
            "name": "14PT",
            "uuid": "6f4fd47a-f70f-4f3d-84f8-a78ef9a62a5a"
        }
    ],
    "coating_list": [
        {
            "name": "UVFR",
            "uuid": "1e8116af-acfc-44b1-83dc-8181aa338834"
        }
    ],
    "products": [
        {
            "product_uuid": "817487fd-96e8-4053-82a2-734a6e40693a",
            "product_code": "14PT-BCUVFR-1.5X3.5",
            "product_description": "1.5\" X 3.5\" 14PT Business Cards with Full UV on the front only, No UV coating on the back"
        }
    ]
}
